"""
Generates the attack animations for the UE5 mannequin skeleton as Animation Sequences:
  /Game/Weapons/Sword/Anims/AS_SwordSlash            one-handed diagonal slash
  /Game/Weapons/Greatsword/Anims/AS_GreatswordSlash  two-handed diagonal slash
Both cut from the upper right to the lower left, in front of the body.

The motion is authored procedurally:
  - pelvis shift/turn with the feet kept planted (leg IK),
  - torso twist and lean, head kept looking forward,
  - analytic two-bone IK for the right arm with an anatomically consistent elbow hinge;
    the elbow direction is chosen per key to keep wrist bend and forearm twist small,
  - wrist orientation that keeps the blade edge in the slash plane,
  - for the two-handed sword, the left hand follows the grip below the right hand,
  - forearm twist spread over the twist bones, and closed fists on the grips.

Run (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/create_attack_anims.py -unattended -nosplash -NullRHI

Environment variables:
  SLASH_PREVIEW=1     only write the stick-figure previews (Saved/<name>_Preview.png: back view,
                      right-side view, top view) without touching assets
  SLASH_ONLY=<name>   only generate the animation with this asset name

Character space: +Y forward, +Z up, -X is the character's right side.
Sword in hand_r bone space: blade = +Z, flat side normal = Y, fingers = -X.
"""
import math
import os
import struct
import zlib

import unreal

PREVIEW_ONLY = os.environ.get("SLASH_PREVIEW") == "1"

IDLE_ANIM = "/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle"
FPS = 60

RIGHT = (-1.0, 0.0, 0.0)
FWD = (0.0, 1.0, 0.0)
UP = (0.0, 0.0, 1.0)
DOWN = (0.0, 0.0, -1.0)

# ---------------------------------------------------------------- vector / quaternion math (x, y, z, w)

def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def length(a): return math.sqrt(dot(a, a))


def norm(a):
    n = length(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-9 else (0.0, 0.0, 0.0)


def reject(a, direction):
    """Component of a perpendicular to the unit vector direction."""
    return sub(a, mul(direction, dot(a, direction)))


def lerp(a, b, t): return add(mul(a, 1.0 - t), mul(b, t))


def qmul(a, b):
    """Hamilton product: rotate by b first, then by a."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qconj(q): return (-q[0], -q[1], -q[2], q[3])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q))
    return tuple(c / n for c in q)


def qrot(q, v):
    u = (q[0], q[1], q[2])
    t = mul(cross(u, v), 2.0)
    return add(add(v, mul(t, q[3])), cross(u, t))


def qaxis(axis, degrees):
    a = norm(axis)
    h = math.radians(degrees) * 0.5
    s = math.sin(h)
    return (a[0] * s, a[1] * s, a[2] * s, math.cos(h))


def qfrom_axes(x, y, z):
    """Quaternion of the rotation whose matrix columns are the (orthonormal) axes x, y, z."""
    m00, m10, m20 = x
    m01, m11, m21 = y
    m02, m12, m22 = z
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        q = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        q = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        q = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
    return qnorm(q)


def frame(direction, normal):
    """Rotation with X along direction and Z along normal (made perpendicular to direction)."""
    x = norm(direction)
    z = norm(reject(normal, x))
    return qfrom_axes(x, cross(z, x), z)


def qslerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b = tuple(-c for c in b)
        d = -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(d)
    sa = math.sin((1 - t) * th) / math.sin(th)
    sb = math.sin(t * th) / math.sin(th)
    return tuple(x * sa + y * sb for x, y in zip(a, b))


def angle_between(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(norm(a), norm(b))))))


def rot_toward(axis, degrees, start, toward):
    """Rotation about axis by |degrees| whose sign turns `start` toward `toward` for positive degrees."""
    if dot(qrot(qaxis(axis, 10.0), start), toward) < 0:
        return qaxis(axis, -degrees)
    return qaxis(axis, degrees)


def catmull(values, u, combine):
    """Catmull-Rom through `values` at integer parameters."""
    n = len(values)
    i = max(0, min(n - 2, int(math.floor(u))))
    t = u - i
    p0 = values[max(0, i - 1)]
    p1 = values[i]
    p2 = values[i + 1]
    p3 = values[min(n - 1, i + 2)]
    w0 = -0.5 * t ** 3 + t ** 2 - 0.5 * t
    w1 = 1.5 * t ** 3 - 2.5 * t ** 2 + 1.0
    w2 = -1.5 * t ** 3 + 2.0 * t ** 2 + 0.5 * t
    w3 = 0.5 * t ** 3 - 0.5 * t ** 2
    return combine([(w0, p0), (w1, p1), (w2, p2), (w3, p3)])


def combine_vec(items):
    out = (0.0, 0.0, 0.0)
    for w, v in items:
        out = add(out, mul(v, w))
    return out


def combine_scalar(items):
    return sum(w * v for w, v in items)


# ---------------------------------------------------------------- skeleton / base pose

def to_vec(v): return (v.x, v.y, v.z)
def to_quat(q): return qnorm((q.x, q.y, q.z, q.w))


class Rig:
    def __init__(self, idle_anim):
        ext = unreal.AnimPoseExtensions
        pose = ext.get_anim_pose_at_frame(idle_anim, 0, unreal.AnimPoseEvaluationOptions())
        self.bones = [str(n) for n in ext.get_bone_names(pose)]
        self.parent = {}
        self.base = {}
        self.scale = {}
        for bone in self.bones:
            path = [str(n) for n in unreal.AnimationLibrary.find_bone_path_to_root(idle_anim, bone)]
            self.parent[bone] = path[1] if len(path) > 1 else None
            t = ext.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
            self.base[bone] = (to_vec(t.translation), to_quat(t.rotation))
            self.scale[bone] = to_vec(t.scale3d)
        order = {bone: i for i, bone in enumerate(self.bones)}
        for bone in self.bones:
            parent = self.parent[bone]
            if parent is not None and order[parent] > order[bone]:
                raise RuntimeError("Bone order is not parent-first: " + bone)
        self.idle_world = self.fk(dict(self.base))

    def fk(self, local):
        world = {}
        for bone in self.bones:
            pos, rot = local[bone]
            parent = self.parent[bone]
            if parent is None:
                world[bone] = (pos, rot)
            else:
                ppos, prot = world[parent]
                world[bone] = (add(ppos, qrot(prot, pos)), qnorm(qmul(prot, rot)))
        return world

    def set_world_rot(self, local, world, bone, rot):
        parent = self.parent[bone]
        prot = world[parent][1] if parent else (0.0, 0.0, 0.0, 1.0)
        local[bone] = (local[bone][0], qnorm(qmul(qconj(prot), rot)))

    def set_world(self, local, world, bone, pos, rot):
        parent = self.parent[bone]
        ppos, prot = world[parent] if parent else ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))
        local[bone] = (qrot(qconj(prot), sub(pos, ppos)), qnorm(qmul(qconj(prot), rot)))


def swivel_reference(direction):
    ref = reject(DOWN, direction)
    if length(ref) < 0.15:
        ref = reject(mul(FWD, -1.0), direction)
    return norm(ref)


def swivel_of(direction, pole):
    ref = swivel_reference(direction)
    return math.degrees(math.atan2(dot(pole, cross(direction, ref)), dot(pole, ref)))


def pole_from_swivel(direction, degrees):
    return qrot(qaxis(direction, degrees), swivel_reference(direction))


class Limb:
    """Two-bone chain solved analytically; keeps the joint's hinge axis as it is in the idle pose."""

    def __init__(self, rig, upper, mid, end, max_stretch):
        self.upper, self.mid, self.end = upper, mid, end
        self.max_stretch = max_stretch
        w = rig.idle_world
        s, e, t = w[upper][0], w[mid][0], w[end][0]
        self.upper_len = length(sub(e, s))
        self.lower_len = length(sub(t, e))
        direction = norm(sub(t, s))
        self.idle_pole = norm(reject(sub(e, s), direction))
        normal = cross(self.idle_pole, direction)
        self.upper_offset = qmul(qconj(frame(sub(e, s), normal)), w[upper][1])
        self.lower_offset = qmul(qconj(frame(sub(t, e), normal)), w[mid][1])
        self.idle_swivel = swivel_of(direction, self.idle_pole)

    def solve(self, rig, local, target, pole=None, swivel=None):
        """Returns (reached end position, mid joint position)."""
        world = rig.fk(local)
        start = world[self.upper][0]
        to_target = sub(target, start)
        dist = max(abs(self.upper_len - self.lower_len) + 1.0,
                   min(length(to_target), (self.upper_len + self.lower_len) * self.max_stretch))
        direction = norm(to_target)
        target = add(start, mul(direction, dist))
        along = (dist * dist + self.upper_len ** 2 - self.lower_len ** 2) / (2.0 * dist)
        height = math.sqrt(max(0.0, self.upper_len ** 2 - along * along))
        if pole is None:
            pole = pole_from_swivel(direction, swivel)
        pole = norm(reject(pole, direction))
        mid = add(add(start, mul(direction, along)), mul(pole, height))
        normal = cross(pole, direction)
        rig.set_world_rot(local, world, self.upper, qmul(frame(sub(mid, start), normal), self.upper_offset))
        world = rig.fk(local)
        rig.set_world_rot(local, world, self.mid, qmul(frame(sub(target, mid), normal), self.lower_offset))
        return target, mid


# ---------------------------------------------------------------- the motion

# Slash direction: from the upper right to the lower left. The slash plane contains this and "forward".
SLASH_DIR = norm((0.72, 0.0, -0.69))
PLANE_NORMAL = norm(cross(SLASH_DIR, FWD))


def in_plane(forward, along_slash):
    return norm(add(mul(FWD, forward), mul(SLASH_DIR, along_slash)))


IDLE = dict(hand=None, blade=None, twist=0.0, lean=0.0, pelvis_yaw=0.0, pelvis=(0.0, 0.0, 0.0))

# keys:
#   t           time [s]
#   hand        right wrist target; blade = wanted blade direction (None = idle pose). The real blade direction
#               stays in the slash plane at an angle to the forearm that a wrist can hold, as close as possible.
#   twist       spine twist to the right [deg]; lean = spine lean forward [deg]
#   pelvis_yaw  pelvis turn to the right [deg]; pelvis = pelvis offset (x: -right/+left, y: forward, z: up) [cm]
# key_speed:    speed of the path parameter at each key (keys per second): slow at the top, fastest through the cut
# hit_time / combo_time are only reported; the character's loadout uses the same values.
ATTACKS = [
    dict(
        name="AS_SwordSlash", out_dir="/Game/Weapons/Sword/Anims", two_handed=False,
        blade_tip=88.4, pommel=9.0, hit_time=0.38, combo_time=0.66,
        keys=[
            dict(IDLE, t=0.00),
            # Wind-up: sword raised over the right shoulder, weight back, chest opened to the right
            dict(t=0.27, hand=(-33.0, -5.0, 161.0), blade=in_plane(-0.6, -0.8),
                 twist=21.0, lean=-4.0, pelvis_yaw=9.0, pelvis=(-1.5, -3.0, -1.0)),
            # Impact: arm extended in front of the chest, blade leading forward
            dict(t=0.37, hand=(-4.0, 39.0, 118.0), blade=in_plane(1.0, -0.30),
                 twist=-2.0, lean=6.0, pelvis_yaw=-2.0, pelvis=(1.0, 4.0, -3.0)),
            # End of the cut: hand crossing to the left hip, blade forward-left-down
            dict(t=0.46, hand=(11.0, 33.0, 104.0), blade=in_plane(0.75, 0.65),
                 twist=-19.0, lean=11.0, pelvis_yaw=-11.0, pelvis=(2.5, 6.0, -4.5)),
            # Follow-through: arm across the body, tip low on the left
            dict(t=0.57, hand=(24.0, 18.0, 100.0), blade=in_plane(0.55, 0.83),
                 twist=-23.0, lean=11.0, pelvis_yaw=-13.0, pelvis=(2.5, 6.0, -4.5)),
            dict(IDLE, t=1.00),
        ],
        key_speed=[0.0, 2.0, 13.0, 7.0, 0.8, 0.0],
    ),
    dict(
        # Two-handed: the right hand is under the guard, the left hand holds the grip `left_grip` cm below it.
        name="AS_GreatswordSlash", out_dir="/Game/Weapons/Greatsword/Anims", two_handed=True,
        blade_tip=117.8, pommel=27.0, left_grip=-13.0, hit_time=0.47, combo_time=0.84,
        keys=[
            dict(IDLE, t=0.00),
            # Wind-up: both hands at the right shoulder, blade back over it, hips and chest turned right
            dict(t=0.34, hand=(-22.0, 0.0, 157.0), blade=in_plane(-0.6, -0.8),
                 twist=24.0, lean=-5.0, pelvis_yaw=13.0, pelvis=(-2.0, -4.0, -1.5)),
            # Impact: both arms pushed forward in front of the chest
            dict(t=0.46, hand=(-3.0, 37.0, 122.0), blade=in_plane(1.0, -0.30),
                 twist=-4.0, lean=8.0, pelvis_yaw=-3.0, pelvis=(1.0, 5.0, -4.0)),
            # End of the cut: hands at the left hip, weight on the front leg
            dict(t=0.56, hand=(9.0, 32.0, 104.0), blade=in_plane(0.75, 0.65),
                 twist=-22.0, lean=13.0, pelvis_yaw=-13.0, pelvis=(3.0, 7.0, -6.0)),
            # Follow-through
            dict(t=0.69, hand=(17.0, 23.0, 99.0), blade=in_plane(0.6, 0.8),
                 twist=-27.0, lean=13.0, pelvis_yaw=-15.0, pelvis=(3.0, 7.0, -6.0)),
            dict(IDLE, t=1.30),
        ],
        key_speed=[0.0, 1.5, 11.0, 6.0, 0.7, 0.0],
    ),
]

# Angles between forearm and blade a wrist can hold in a hammer grip (90 = neutral wrist)
WRIST_ANGLES = [58.0, 66.0, 74.0, 82.0, 90.0, 98.0, 106.0]
SPINE = ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05"]
NECK = ["neck_01", "neck_02", "head"]
FINGER_CURL = {"01": 62.0, "02": 88.0, "03": 55.0}
FINGERS = ["index", "middle", "ring", "pinky"]

# HandGrip_R / HandGrip_L sockets relative to hand_r / hand_l (from the mannequin skeleton).
# In socket space: +Z = thumb side (blade direction), +Y = fingers.
GRIP_OFFSET = {"r": (-7.012134, 2.048732, 0.0), "l": (7.520928, -2.529256, 0.0)}
SOCKET_ROT = {"r": (0.0, 0.0, 0.70710678, 0.70710678), "l": (-0.70710678, -0.70710678, 0.0, 0.0)}
FINGER_AXIS = {"r": (-1.0, 0.0, 0.0), "l": (1.0, 0.0, 0.0)}   # direction of the fingers in hand space


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


class Motion:
    def __init__(self, rig, attack):
        self.rig = rig
        self.attack = attack
        self.keys = attack["keys"]
        self.arm = Limb(rig, "upperarm_r", "lowerarm_r", "hand_r", 0.985)
        self.arm_l = Limb(rig, "upperarm_l", "lowerarm_l", "hand_l", 0.985)
        self.legs = [Limb(rig, "thigh_{}".format(s), "calf_{}".format(s), "foot_{}".format(s), 0.9995) for s in "lr"]
        # Palm normal in hand space: the +/-Y axis that faces the body in the idle pose
        self.palm = {}
        for side in "lr":
            pos, rot = rig.idle_world["hand_" + side]
            inward = (-1.0 if pos[0] > 0 else 1.0, 0.0, 0.0)
            self.palm[side] = (0.0, 1.0, 0.0) if dot(qrot(rot, (0.0, 1.0, 0.0)), inward) > 0 else (0.0, -1.0, 0.0)
        self.key_hands = None
        self.key_poles = None
        self.key_rolls = None
        self.key_poles_l = None
        self.plan()
        if attack["two_handed"]:
            self.plan_left()

    def time_to_param(self, t):
        """Cubic Hermite mapping time -> key parameter with the speeds in key_speed."""
        keys, speed = self.keys, self.attack["key_speed"]
        for i in range(len(keys) - 1):
            t0, t1 = keys[i]["t"], keys[i + 1]["t"]
            if t <= t1 or i == len(keys) - 2:
                h = t1 - t0
                s = max(0.0, min(1.0, (t - t0) / h))
                m0, m1 = speed[i] * h, speed[i + 1] * h
                h00 = 2 * s ** 3 - 3 * s ** 2 + 1
                h10 = s ** 3 - 2 * s ** 2 + s
                h01 = -2 * s ** 3 + 3 * s ** 2
                h11 = s ** 3 - s ** 2
                return max(float(i), min(float(i + 1), i * h00 + m0 * h10 + (i + 1) * h01 + m1 * h11))
        return float(len(keys) - 1)

    # ---- body

    def apply_fist(self, local, side):
        """Curl the fingers around the grip (rotation about each finger bone's own Z axis)."""
        rig = self.rig
        world = rig.fk(local)
        palm = qrot(world["hand_" + side][1], self.palm[side])
        for finger in FINGERS:
            for joint, degrees in FINGER_CURL.items():
                bone = "{}_{}_{}".format(finger, joint, side)
                pos, rot = local[bone]
                parent_rot = world[rig.parent[bone]][1]
                best = None
                # Pick the sign that bends the finger toward the palm.
                for sign in (1.0, -1.0):
                    candidate = qnorm(qmul(rot, qaxis((0.0, 0.0, 1.0), sign * degrees)))
                    score = dot(qrot(qmul(parent_rot, candidate), FINGER_AXIS[side]), palm)
                    if best is None or score > best[0]:
                        best = (score, candidate)
                local[bone] = (pos, best[1])
                world = rig.fk(local)

    def apply_pelvis(self, local, yaw, offset):
        """Moves/turns the pelvis and keeps both feet where they are in the idle pose."""
        rig = self.rig
        pos, rot = local["pelvis"]
        local["pelvis"] = (add(pos, offset), rot)
        world = rig.fk(local)
        rig.set_world_rot(local, world, "pelvis", qmul(rot_toward(UP, yaw, FWD, RIGHT), world["pelvis"][1]))
        for leg in self.legs:
            foot_pos, foot_rot = rig.idle_world[leg.end]
            leg.solve(rig, local, foot_pos, pole=leg.idle_pole)
            world = rig.fk(local)
            rig.set_world_rot(local, world, leg.end, foot_rot)

    def apply_torso(self, local, twist, lean, total_yaw):
        rig = self.rig
        step = qmul(rot_toward(UP, twist / len(SPINE), FWD, RIGHT), rot_toward(RIGHT, lean / len(SPINE), UP, FWD))
        for bone in SPINE:
            world = rig.fk(local)
            rig.set_world_rot(local, world, bone, qmul(step, world[bone][1]))
        # Keep the head looking mostly forward
        counter = qmul(rot_toward(UP, -0.75 * total_yaw / len(NECK), FWD, RIGHT),
                       rot_toward(RIGHT, -0.6 * lean / len(NECK), UP, FWD))
        for bone in NECK:
            world = rig.fk(local)
            rig.set_world_rot(local, world, bone, qmul(counter, world[bone][1]))

    def body_pose(self, u):
        keys = self.keys
        local = dict(self.rig.base)
        twist = catmull([k["twist"] for k in keys], u, combine_scalar)
        lean = catmull([k["lean"] for k in keys], u, combine_scalar)
        pelvis_yaw = catmull([k["pelvis_yaw"] for k in keys], u, combine_scalar)
        pelvis = catmull([k["pelvis"] for k in keys], u, combine_vec)
        self.apply_fist(local, "r")
        self.apply_fist(local, "l")
        self.apply_pelvis(local, pelvis_yaw, pelvis)
        self.apply_torso(local, twist, lean, twist + pelvis_yaw)
        return local

    # ---- arms and hands

    @staticmethod
    def blades_in_plane(forearm, wrist_angle):
        """Blade directions lying in the slash plane at the given angle from the forearm (0-2 solutions)."""
        projected = reject(forearm, PLANE_NORMAL)
        size = length(projected)
        if size < 1e-3:
            return []
        c = math.cos(math.radians(wrist_angle)) / size
        if abs(c) > 1.0:
            return []
        e1 = mul(projected, 1.0 / size)
        e2 = cross(PLANE_NORMAL, e1)
        alpha = math.acos(c)
        return [norm(add(mul(e1, math.cos(alpha)), mul(e2, sign * math.sin(alpha)))) for sign in (1.0, -1.0)]

    @staticmethod
    def hand_rotation(blade, flat_normal, forearm):
        """World rotation of hand_r: blade along +Z, flat side normal along +/-Y. Returns (rotation, wrist bend)."""
        best = None
        for sign in (1.0, -1.0):
            y = norm(reject(mul(flat_normal, sign), blade))
            x = norm(cross(y, blade))
            bend = angle_between(mul(x, -1.0), forearm)   # fingers (-X) vs forearm direction
            if best is None or bend < best[1]:
                best = (qfrom_axes(x, y, blade), bend)
        return best

    def forearm_twist(self, local, side="r"):
        """Rotation of the hand about the forearm axis relative to the idle pose [deg]."""
        rel = qmul(local["hand_" + side][1], qconj(self.rig.base["hand_" + side][1]))
        if rel[3] < 0:
            rel = tuple(-c for c in rel)
        return math.degrees(2.0 * math.atan2(rel[0], rel[3]))

    def wrist_bend(self, world, side="r"):
        forearm = norm(sub(world["hand_" + side][0], world["lowerarm_" + side][0]))
        return angle_between(qrot(world["hand_" + side][1], FINGER_AXIS[side]), forearm)

    def spread_forearm_twist(self, local, side="r"):
        twist = self.forearm_twist(local, side)
        limb = self.arm if side == "r" else self.arm_l
        for bone in ("lowerarm_twist_01_" + side, "lowerarm_twist_02_" + side):
            if bone in local:
                pos = self.rig.base[bone][0]
                fraction = min(1.0, length(pos) / limb.lower_len)
                local[bone] = (pos, qnorm(qmul(qaxis((1.0, 0.0, 0.0), twist * fraction), self.rig.base[bone][1])))
        return twist

    def plan(self):
        """Chooses the right elbow direction and hand rotation at every key."""
        rig = self.rig
        hands, poles = [], []
        previous = self.arm.idle_pole
        for index, key in enumerate(self.keys):
            if key["blade"] is None:
                hands.append(rig.base["hand_r"][1])
                poles.append(self.arm.idle_pole)
                previous = self.arm.idle_pole
                continue
            body = self.body_pose(float(index))
            shoulder = rig.fk(body)["upperarm_r"][0]
            direction = norm(sub(key["hand"], shoulder))
            best = None
            for swivel in range(-180, 180, 4):
                pole = pole_from_swivel(direction, float(swivel))
                local = dict(body)
                _, elbow = self.arm.solve(rig, local, key["hand"], pole=pole)
                world = rig.fk(local)
                forearm = norm(sub(world["hand_r"][0], world["lowerarm_r"][0]))
                elbow_cost = (0.2 * angle_between(pole, previous)) ** 2
                elbow_cost += (8.0 * max(0.0, elbow[2] - shoulder[2] - 6.0)) ** 2     # elbow far above the shoulder
                elbow_cost += (8.0 * max(0.0, elbow[0] - shoulder[0] - 4.0)) ** 2     # elbow pushed into the torso
                for wrist_angle in WRIST_ANGLES:
                    for blade in self.blades_in_plane(forearm, wrist_angle):
                        rot, bend = self.hand_rotation(blade, PLANE_NORMAL, forearm)
                        trial = dict(local)
                        rig.set_world_rot(trial, world, "hand_r", rot)
                        twist = self.forearm_twist(trial)
                        off = angle_between(blade, key["blade"])
                        cost = elbow_cost + bend ** 2 + (0.45 * twist) ** 2 + (1.0 * off) ** 2
                        if best is None or cost < best[0]:
                            # Keep the hand rotation relative to the forearm: the wrist then moves smoothly between keys
                            best = (cost, pole, trial["hand_r"][1], bend, twist, wrist_angle, off, swivel, elbow)
            _, pole, rot, bend, twist, wrist_angle, off, swivel, elbow = best
            unreal.log_warning("SLASH {} key {} t={:.2f}: R elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg "
                               "forearm_twist={:.0f}deg blade_vs_forearm={:.0f}deg blade_off_wanted={:.0f}deg".format(
                                   self.attack["name"], index, key["t"], elbow[0], elbow[1], elbow[2], bend, twist, wrist_angle, off))
            hands.append(rot)
            poles.append(pole)
            previous = pole
        for index in range(1, len(hands)):
            if sum(a * b for a, b in zip(hands[index - 1], hands[index])) < 0:
                hands[index] = tuple(-c for c in hands[index])
        self.key_hands, self.key_poles = hands, poles

    def left_hand_goal(self, world, roll):
        """Wrist position and rotation of hand_l gripping the handle below the right hand.
        roll = rotation of the left hand around the handle relative to the right hand [deg]."""
        pos, rot = world["hand_r"]
        socket_r = qmul(rot, SOCKET_ROT["r"])
        axis = qrot(socket_r, (0.0, 0.0, 1.0))
        point = add(add(pos, qrot(rot, GRIP_OFFSET["r"])), mul(axis, self.attack["left_grip"]))
        x = qrot(qaxis(axis, roll), qrot(socket_r, (1.0, 0.0, 0.0)))
        socket_l = qfrom_axes(x, cross(axis, x), axis)
        hand_rot = qnorm(qmul(socket_l, qconj(SOCKET_ROT["l"])))
        return sub(point, qrot(hand_rot, GRIP_OFFSET["l"])), hand_rot

    def plan_left(self):
        """Chooses how the left hand sits around the handle (one roll for the whole attack: hands do not
        re-grip mid-swing) and the left elbow direction at every key."""
        rig = self.rig
        attack_keys = [i for i, key in enumerate(self.keys) if key["blade"] is not None]
        bases = {i: self.pose(float(i), left=False) for i in attack_keys}

        def candidates(index, roll):
            """(cost, pole, bend, twist, miss, elbow) for every elbow swivel at this key and roll."""
            base_local, base_world, _ = bases[index]
            shoulder = base_world["upperarm_l"][0]
            wrist, hand_rot = self.left_hand_goal(base_world, float(roll))
            direction = norm(sub(wrist, shoulder))
            result = []
            for swivel in range(-180, 180, 6):
                pole = pole_from_swivel(direction, float(swivel))
                local = dict(base_local)
                reached, elbow = self.arm_l.solve(rig, local, wrist, pole=pole)
                world = rig.fk(local)
                rig.set_world_rot(local, world, "hand_l", hand_rot)
                bend = angle_between(qrot(hand_rot, FINGER_AXIS["l"]), norm(sub(reached, elbow)))
                twist = self.forearm_twist(local, "l")
                miss = length(sub(reached, wrist))
                cost = bend ** 2 + (0.45 * twist) ** 2 + (25.0 * miss) ** 2
                cost += (2.0 * max(0.0, abs(twist) - 95.0)) ** 2                 # beyond what a forearm can turn
                cost += (2.0 * max(0.0, bend - 55.0)) ** 2                       # beyond what a wrist can bend
                cost += (8.0 * max(0.0, elbow[2] - shoulder[2] - 6.0)) ** 2      # elbow far above the shoulder
                cost += (4.0 * max(0.0, elbow[0] - shoulder[0] - 14.0)) ** 2     # elbow winged far out to the left
                inward = max(0.0, shoulder[0] - elbow[0] - 4.0)                  # elbow moved toward the right side...
                if elbow[1] - shoulder[1] < 12.0:                                 # ...and not in front of the body
                    cost += (8.0 * inward) ** 2
                result.append((cost, pole, bend, twist, miss, elbow))
            return result

        best_roll = None
        for roll in range(-180, 180, 15):
            total = sum(min(c[0] for c in candidates(index, roll)) for index in attack_keys)
            if best_roll is None or total < best_roll[0]:
                best_roll = (total, roll)
        base_roll = best_roll[1]

        rolls = [None] * len(self.keys)
        poles = [None] * len(self.keys)
        previous = None
        for index in attack_keys:
            # The hand may turn a little around the handle during the swing, as a real grip does
            options = []
            for delta in (-45, -30, -15, 0, 15, 30, 45):
                for c in candidates(index, base_roll + delta):
                    cost = c[0] + (0.4 * delta) ** 2
                    if previous is not None:
                        cost += (0.3 * angle_between(c[1], previous)) ** 2
                    options.append((cost, base_roll + delta) + c[1:])
            _, roll, pole, bend, twist, miss, elbow = min(options, key=lambda c: c[0])
            unreal.log_warning("SLASH {} key {} t={:.2f}: L roll={}deg elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg "
                               "forearm_twist={:.0f}deg miss={:.1f}cm".format(
                                   self.attack["name"], index, self.keys[index]["t"], roll, elbow[0], elbow[1], elbow[2], bend, twist, miss))
            rolls[index] = float(roll)
            poles[index] = pole
            previous = pole
        # Idle keys (hand not on the sword yet / any more) reuse the nearest attack key
        valid = [i for i, r in enumerate(rolls) if r is not None]
        for i in range(len(rolls)):
            if rolls[i] is None:
                nearest = min(valid, key=lambda j: abs(j - i))
                rolls[i], poles[i] = rolls[nearest], poles[nearest]
        self.key_rolls, self.key_poles_l = rolls, poles

    def attach_weight(self, u):
        """How firmly the left hand is on the handle: 0 at the idle keys, 1 during the attack."""
        last = len(self.keys) - 1
        return min(smoothstep(u / 0.75), smoothstep((last - u) / 0.75))

    def pose(self, u, left=True):
        """Full local pose at path parameter u (0 .. len(keys)-1). Returns (local, world, info)."""
        rig, keys = self.rig, self.keys
        local = self.body_pose(u)
        positions = [k["hand"] if k["hand"] else rig.idle_world["hand_r"][0] for k in keys]
        target = catmull(positions, u, combine_vec)
        self.arm.solve(rig, local, target, pole=norm(catmull(self.key_poles, u, combine_vec)))

        i = max(0, min(len(keys) - 2, int(math.floor(u))))
        local["hand_r"] = (local["hand_r"][0], qslerp(self.key_hands[i], self.key_hands[i + 1], u - i))
        twist = self.spread_forearm_twist(local, "r")
        world = rig.fk(local)
        info = dict(twist=twist, bend=self.wrist_bend(world, "r"), left_miss=0.0, left_bend=0.0, left_twist=0.0)

        if left and self.attack["two_handed"]:
            attach = self.attach_weight(u)
            if attach > 0.0:
                wrist, hand_rot = self.left_hand_goal(world, catmull(self.key_rolls, u, combine_scalar))
                free_wrist, free_rot = world["hand_l"]
                shoulder = world["upperarm_l"][0]
                free_pole = reject(sub(world["lowerarm_l"][0], shoulder), norm(sub(free_wrist, shoulder)))
                key_pole = norm(catmull(self.key_poles_l, u, combine_vec))
                goal = lerp(free_wrist, wrist, attach)
                reached, _ = self.arm_l.solve(rig, local, goal, pole=norm(lerp(norm(free_pole), key_pole, attach)))
                world = rig.fk(local)
                rig.set_world_rot(local, world, "hand_l", qslerp(free_rot, hand_rot, attach))
                info["left_twist"] = self.spread_forearm_twist(local, "l")
                world = rig.fk(local)
                info["left_bend"] = self.wrist_bend(world, "l")
                if attach > 0.999:
                    info["left_miss"] = length(sub(reached, goal))

        # IK helper bones follow the hands
        for ik_bone, source in (("ik_hand_gun", "hand_r"), ("ik_hand_r", "hand_r"), ("ik_hand_l", "hand_l")):
            if ik_bone in local:
                rig.set_world(local, world, ik_bone, world[source][0], world[source][1])
                world = rig.fk(local)
        return local, world, info

    def sword_points(self, world):
        pos, rot = world["hand_r"]
        grip = add(pos, qrot(rot, GRIP_OFFSET["r"]))
        axis = qrot(rot, (0.0, 0.0, 1.0))
        return add(grip, mul(axis, -self.attack["pommel"])), add(grip, mul(axis, self.attack["blade_tip"]))


# ---------------------------------------------------------------- preview image

class Canvas:
    def __init__(self, width, height):
        self.w, self.h = width, height
        self.px = bytearray([255]) * (width * height * 3)

    def dot(self, x, y, color, size=1):
        for dy in range(-size, size + 1):
            for dx in range(-size, size + 1):
                xx, yy = int(x) + dx, int(y) + dy
                if 0 <= xx < self.w and 0 <= yy < self.h:
                    i = (yy * self.w + xx) * 3
                    self.px[i:i + 3] = bytes(color)

    def line(self, a, b, color, size=1):
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1))
        for s in range(steps + 1):
            t = s / steps
            self.dot(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, color, size)

    def save(self, path):
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


BODY_LINES = [
    (["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"], (90, 90, 90)),
    (["pelvis", "thigh_l", "calf_l", "foot_l", "ball_l"], (160, 160, 160)),
    (["pelvis", "thigh_r", "calf_r", "foot_r", "ball_r"], (110, 110, 110)),
    (["spine_05", "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l"], (60, 160, 60)),
    (["spine_05", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r"], (40, 90, 220)),
]


def draw_preview(motion, times, path):
    cell_w, cell_h = 230, 270
    canvas = Canvas(cell_w * len(times), cell_h * 3)
    # back view (character's right on the right), right-side view (forward on the right), top view (forward up)
    views = [
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - 30 + p[1], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h / 2 + 40 - p[1]),
    ]
    for column, t in enumerate(times):
        _, world, _ = motion.pose(motion.time_to_param(t))
        pommel, tip = motion.sword_points(world)
        for row, view in enumerate(views):
            ox, oy = column * cell_w, row * cell_h
            canvas.line((ox, oy), (ox, oy + cell_h), (220, 220, 220))
            canvas.line((ox, oy + cell_h - 1), (ox + cell_w, oy + cell_h - 1), (220, 220, 220))
            for chain, color in BODY_LINES:
                for a, b in zip(chain, chain[1:]):
                    canvas.line(view(world[a][0], ox, oy), view(world[b][0], ox, oy), color, 1)
            head = view(add(world["head"][0], (0, 0, 10)), ox, oy)
            for ang in range(0, 360, 12):
                canvas.dot(head[0] + 9 * math.cos(math.radians(ang)), head[1] + 9 * math.sin(math.radians(ang)), (90, 90, 90), 0)
            canvas.line(view(pommel, ox, oy), view(tip, ox, oy), (220, 30, 30), 1)
            canvas.dot(*view(tip, ox, oy), (220, 30, 30), 2)
    canvas.save(path)
    unreal.log_warning("SLASH preview written to " + path)


def segment_distance(p1, q1, p2, q2):
    """Closest distance between two segments (sampled; good enough for a sanity check)."""
    best = 1e9
    for i in range(21):
        a = lerp(p1, q1, i / 20.0)
        for j in range(11):
            best = min(best, length(sub(a, lerp(p2, q2, j / 10.0))))
    return best


def body_clearance(motion, world):
    """Closest distance of the blade to the body (the left arm is skipped when it holds the sword)."""
    pommel, tip = motion.sword_points(world)
    total = motion.attack["pommel"] + motion.attack["blade_tip"]
    blade_start = lerp(pommel, tip, (motion.attack["pommel"] + 14.0) / total)
    segments = [("pelvis", "spine_03"), ("spine_03", "neck_01"), ("neck_01", "head"), ("thigh_l", "calf_l"),
                ("thigh_r", "calf_r"), ("calf_l", "foot_l"), ("calf_r", "foot_r")]
    if not motion.attack["two_handed"]:
        segments += [("upperarm_l", "lowerarm_l"), ("lowerarm_l", "hand_l")]
    worst = (1e9, "")
    for a, b in segments:
        d = segment_distance(blade_start, tip, world[a][0], world[b][0])
        if d < worst[0]:
            worst = (d, a)
    return worst


# ---------------------------------------------------------------- asset writing

def compare_with_existing(rig, attack, frames):
    """Logs how far the new frames are from the asset that is already on disk (0 = unchanged motion)."""
    path = attack["out_dir"] + "/" + attack["name"]
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return
    existing = unreal.load_asset(path)
    ext = unreal.AnimPoseExtensions
    worst_pos = worst_rot = 0.0
    for frame_index in range(0, len(frames), 3):
        pose = ext.get_anim_pose_at_time(existing, frame_index / FPS, unreal.AnimPoseEvaluationOptions())
        world = rig.fk(frames[frame_index])
        for bone in ("hand_r", "lowerarm_r", "spine_05", "pelvis", "head", "foot_l"):
            t = ext.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD)
            worst_pos = max(worst_pos, length(sub(to_vec(t.translation), world[bone][0])))
            d = abs(sum(a * b for a, b in zip(to_quat(t.rotation), world[bone][1])))
            worst_rot = max(worst_rot, math.degrees(2.0 * math.acos(min(1.0, d))))
    unreal.log_warning("SLASH {} vs asset on disk: max difference {:.2f} cm, {:.1f} deg".format(attack["name"], worst_pos, worst_rot))


def write_sequence(rig, idle_anim, attack, frames):
    eal = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    skeleton = idle_anim.get_skeleton() if hasattr(idle_anim, "get_skeleton") else idle_anim.get_editor_property("skeleton")
    path = attack["out_dir"] + "/" + attack["name"]
    # An existing asset is rewritten in place: other assets may reference it, so it can not be deleted.
    existing = eal.does_asset_exist(path)
    if existing:
        sequence = unreal.load_asset(path)
    else:
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", skeleton)
        sequence = tools.create_asset(attack["name"], attack["out_dir"], unreal.AnimSequence, factory)

    tracks = {bone: ([], [], []) for bone in rig.bones}
    for local in frames:
        for bone in rig.bones:
            pos, rot = local[bone]
            p, r, s = tracks[bone]
            p.append(unreal.Vector(*pos))
            r.append(unreal.Quat(rot[0], rot[1], rot[2], rot[3]))
            s.append(unreal.Vector(*rig.scale[bone]))

    controller = sequence.controller
    controller.open_bracket(unreal.Text("Generate sword slash"), False)
    if existing:
        controller.remove_all_bone_tracks(False)
        unreal.AnimationLibrary.remove_all_animation_notify_tracks(sequence)
    controller.set_frame_rate(unreal.FrameRate(FPS, 1), False)
    controller.set_number_of_frames(unreal.FrameNumber(len(frames) - 1), False)
    for bone in rig.bones:
        controller.add_bone_curve(bone, False)
        p, r, s = tracks[bone]
        controller.set_bone_track_keys(bone, p, r, s, False)
    controller.close_bracket(False)
    eal.save_loaded_asset(sequence)
    unreal.log_warning("SLASH created {} ({} frames, {:.2f}s); hit_time={:.2f}s combo_time={:.2f}s".format(
        path, len(frames), sequence.get_play_length(), attack["hit_time"], attack["combo_time"]))


def generate(rig, idle_anim, attack):
    motion = Motion(rig, attack)
    name = attack["name"]

    # The first pose must reproduce the idle pose (apart from the closed fists)
    _, world, _ = motion.pose(0.0)
    error = max(length(sub(world[b][0], rig.idle_world[b][0])) for b in ("hand_r", "lowerarm_r", "hand_l", "foot_l", "foot_r", "head"))
    unreal.log_warning("SLASH {} idle reproduction error {:.3f} cm".format(name, error))

    duration = attack["keys"][-1]["t"]
    count = int(round(duration * FPS))
    if abs(duration * 30.0 - round(duration * 30.0)) > 1e-6:
        # Unreal resamples animations to 30 fps when compressing; other lengths crash the compression.
        raise RuntimeError("{}: the length {}s must be a multiple of 1/30 s".format(name, duration))
    frames = []
    worst = (1e9, "", 0.0)
    peak = dict(twist=0.0, bend=0.0, left_miss=0.0, left_bend=0.0, left_twist=0.0)
    previous = -1.0
    for frame_index in range(count + 1):
        t = frame_index / FPS
        u = motion.time_to_param(t)
        if u < previous - 1e-6:
            raise RuntimeError("Time mapping is not monotone at t={:.3f}".format(t))
        previous = u
        local, world, info = motion.pose(u)
        frames.append(local)
        for k in peak:
            peak[k] = max(peak[k], abs(info[k]))
        clearance = body_clearance(motion, world)
        if clearance[0] < worst[0]:
            worst = (clearance[0], clearance[1], t)
    unreal.log_warning("SLASH {} closest blade-to-body distance {:.1f} cm (near {}) at t={:.2f}s".format(name, *worst))
    unreal.log_warning("SLASH {} right hand: max forearm twist {:.0f}deg, max wrist bend {:.0f}deg".format(name, peak["twist"], peak["bend"]))
    if attack["two_handed"]:
        unreal.log_warning("SLASH {} left hand: max forearm twist {:.0f}deg, max wrist bend {:.0f}deg, max distance from the grip {:.1f} cm".format(
            name, peak["left_twist"], peak["left_bend"], peak["left_miss"]))

    k = [key["t"] for key in attack["keys"]]
    times = [0.0, k[1] * 0.5, k[1], (k[1] + k[2]) * 0.5, k[2], (k[2] + k[3]) * 0.5, k[3], k[4], (k[4] + k[5]) * 0.5]
    draw_preview(motion, times, os.path.join(unreal.Paths.project_saved_dir(), name + "_Preview.png"))
    compare_with_existing(rig, attack, frames)
    if not PREVIEW_ONLY:
        write_sequence(rig, idle_anim, attack, frames)


def main():
    idle_anim = unreal.load_asset(IDLE_ANIM)
    rig = Rig(idle_anim)
    only = os.environ.get("SLASH_ONLY")
    for attack in ATTACKS:
        if only and attack["name"] != only:
            continue
        generate(rig, idle_anim, attack)


main()
