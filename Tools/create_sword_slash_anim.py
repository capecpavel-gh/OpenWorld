"""
Generates a one-handed diagonal sword slash (upper right -> lower left, in front of the body)
for the UE5 mannequin skeleton, as an Animation Sequence + Montage.

The motion is authored procedurally:
  - pelvis shift/turn with the feet kept planted (leg IK),
  - torso twist and lean, head kept looking forward,
  - analytic two-bone IK for the right arm with an anatomically consistent elbow hinge;
    the elbow swivel is chosen per key to keep wrist bend and forearm twist small,
  - wrist orientation that keeps the blade edge in the slash plane,
  - forearm twist spread over the twist bones, and a closed fist on the grip.

Run (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/create_sword_slash_anim.py -unattended -nosplash -NullRHI

Set the environment variable SLASH_PREVIEW=1 to only write the stick-figure preview
(Saved/SwordSlashPreview.png: back view, right-side view, top view) without touching assets.

Character space: +Y forward, +Z up, -X is the character's right side.
Sword in hand_r bone space: blade = +Z, flat side normal = Y, fingers = -X, HandGrip_R socket at (-7, 2, 0).
"""
import math
import os
import struct
import zlib

import unreal

PREVIEW_ONLY = os.environ.get("SLASH_PREVIEW") == "1"

IDLE_ANIM = "/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle"
OUT_DIR = "/Game/Weapons/Sword/Anims"
SEQUENCE_NAME = "AS_SwordSlash"
MONTAGE_NAME = "AM_SwordSlash"
FPS = 60
PREVIEW_PATH = os.path.join(unreal.Paths.project_saved_dir(), "SwordSlashPreview.png")

GRIP_OFFSET = (-7.0, 2.0, 0.0)   # HandGrip_R socket in hand_r space
BLADE_TIP = 88.0                 # from grip centre to blade tip
POMMEL = 9.0

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
# t           time [s]
# hand        wrist target; blade = wanted blade direction (None = idle pose). The real blade direction
#             stays in the slash plane at an angle to the forearm that a wrist can hold, as close as possible.
# twist       spine twist to the right [deg]; lean = spine lean forward [deg]
# pelvis_yaw  pelvis turn to the right [deg]; pelvis = pelvis offset (x: -right/+left, y: forward, z: up) [cm]
KEYS = [
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
]
# Speed of the path parameter at each key (keys per second): slow at the top, fastest through the cut.
KEY_SPEED = [0.0, 2.0, 13.0, 7.0, 0.8, 0.0]
HIT_TIME = 0.38          # hit check (AnimNotify)
COMBO_TIME = 0.66        # from here a queued click chains the next slash

# Angles between forearm and blade a wrist can hold in a hammer grip (90 = neutral wrist)
WRIST_ANGLES = [58.0, 66.0, 74.0, 82.0, 90.0, 98.0, 106.0]
SPINE = ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05"]
NECK = ["neck_01", "neck_02", "head"]
FINGER_CURL = {"01": 62.0, "02": 88.0, "03": 55.0}
FINGERS = ["index", "middle", "ring", "pinky"]
FOREARM_TWIST_BONES = ["lowerarm_twist_01_r", "lowerarm_twist_02_r"]


def time_to_param(t):
    """Cubic Hermite mapping time -> key parameter with the speeds in KEY_SPEED."""
    for i in range(len(KEYS) - 1):
        t0, t1 = KEYS[i]["t"], KEYS[i + 1]["t"]
        if t <= t1 or i == len(KEYS) - 2:
            h = t1 - t0
            s = max(0.0, min(1.0, (t - t0) / h))
            m0, m1 = KEY_SPEED[i] * h, KEY_SPEED[i + 1] * h
            h00 = 2 * s ** 3 - 3 * s ** 2 + 1
            h10 = s ** 3 - 2 * s ** 2 + s
            h01 = -2 * s ** 3 + 3 * s ** 2
            h11 = s ** 3 - s ** 2
            return max(float(i), min(float(i + 1), i * h00 + m0 * h10 + (i + 1) * h01 + m1 * h11))
    return float(len(KEYS) - 1)


class Motion:
    def __init__(self, rig):
        self.rig = rig
        self.arm = Limb(rig, "upperarm_r", "lowerarm_r", "hand_r", 0.985)
        self.legs = [Limb(rig, "thigh_{}".format(s), "calf_{}".format(s), "foot_{}".format(s), 0.9995) for s in "lr"]
        self.key_hands = None
        self.key_poles = None
        self.plan()

    # ---- body

    def apply_fist(self, local):
        """Curl the right hand's fingers around the grip (rotation about each finger bone's own Z axis)."""
        rig = self.rig
        world = rig.fk(local)
        palm = qrot(world["hand_r"][1], (0.0, 1.0, 0.0))
        for finger in FINGERS:
            for joint, degrees in FINGER_CURL.items():
                bone = "{}_{}_r".format(finger, joint)
                pos, rot = local[bone]
                parent_rot = world[rig.parent[bone]][1]
                best = None
                # Fingers point along the bone's -X; pick the sign that bends them toward the palm.
                for sign in (1.0, -1.0):
                    candidate = qnorm(qmul(rot, qaxis((0.0, 0.0, 1.0), sign * degrees)))
                    score = dot(qrot(qmul(parent_rot, candidate), (-1.0, 0.0, 0.0)), palm)
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
        local = dict(self.rig.base)
        twist = catmull([k["twist"] for k in KEYS], u, combine_scalar)
        lean = catmull([k["lean"] for k in KEYS], u, combine_scalar)
        pelvis_yaw = catmull([k["pelvis_yaw"] for k in KEYS], u, combine_scalar)
        pelvis = catmull([k["pelvis"] for k in KEYS], u, combine_vec)
        self.apply_fist(local)
        self.apply_pelvis(local, pelvis_yaw, pelvis)
        self.apply_torso(local, twist, lean, twist + pelvis_yaw)
        return local

    # ---- right arm and hand

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

    def forearm_twist(self, local):
        """Rotation of the hand about the forearm axis relative to the idle pose [deg]."""
        rel = qmul(local["hand_r"][1], qconj(self.rig.base["hand_r"][1]))
        if rel[3] < 0:
            rel = tuple(-c for c in rel)
        return math.degrees(2.0 * math.atan2(rel[0], rel[3]))

    def wrist_bend(self, world):
        forearm = norm(sub(world["hand_r"][0], world["lowerarm_r"][0]))
        return angle_between(qrot(world["hand_r"][1], (-1.0, 0.0, 0.0)), forearm)

    def idle_wrist_bend(self):
        return self.wrist_bend(self.rig.idle_world)

    def spread_forearm_twist(self, local):
        twist = self.forearm_twist(local)
        for bone in FOREARM_TWIST_BONES:
            if bone in local:
                pos = self.rig.base[bone][0]
                fraction = min(1.0, length(pos) / self.arm.lower_len)
                local[bone] = (pos, qnorm(qmul(qaxis((1.0, 0.0, 0.0), twist * fraction), self.rig.base[bone][1])))
        return twist

    def plan(self):
        """Chooses the elbow direction and hand rotation at every key."""
        rig = self.rig
        hands, poles = [], []
        previous = self.arm.idle_pole
        for index, key in enumerate(KEYS):
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
            unreal.log_warning("SLASH key {} t={:.2f}: swivel={}deg elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg "
                               "forearm_twist={:.0f}deg blade_vs_forearm={:.0f}deg blade_off_wanted={:.0f}deg".format(
                                   index, key["t"], swivel, elbow[0], elbow[1], elbow[2], bend, twist, wrist_angle, off))
            hands.append(rot)
            poles.append(pole)
            previous = pole
        for index in range(1, len(hands)):
            if sum(a * b for a, b in zip(hands[index - 1], hands[index])) < 0:
                hands[index] = tuple(-c for c in hands[index])
        self.key_hands, self.key_poles = hands, poles

    def pose(self, u):
        """Full local pose at path parameter u (0 .. len(KEYS)-1). Returns (local, world, info)."""
        rig = self.rig
        local = self.body_pose(u)
        positions = [k["hand"] if k["hand"] else rig.idle_world["hand_r"][0] for k in KEYS]
        target = catmull(positions, u, combine_vec)
        self.arm.solve(rig, local, target, pole=norm(catmull(self.key_poles, u, combine_vec)))

        i = max(0, min(len(KEYS) - 2, int(math.floor(u))))
        local["hand_r"] = (local["hand_r"][0], qslerp(self.key_hands[i], self.key_hands[i + 1], u - i))
        twist = self.spread_forearm_twist(local)
        world = rig.fk(local)

        # IK helper bones follow the hands
        for ik_bone, source in (("ik_hand_gun", "hand_r"), ("ik_hand_r", "hand_r"), ("ik_hand_l", "hand_l")):
            if ik_bone in local:
                rig.set_world(local, world, ik_bone, world[source][0], world[source][1])
                world = rig.fk(local)
        return local, world, dict(twist=twist, bend=self.wrist_bend(world))


def sword_points(world):
    pos, rot = world["hand_r"]
    grip = add(pos, qrot(rot, GRIP_OFFSET))
    axis = qrot(rot, (0.0, 0.0, 1.0))
    return add(grip, mul(axis, -POMMEL)), add(grip, mul(axis, BLADE_TIP))


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


def draw_preview(motion, times):
    cell_w, cell_h = 230, 250
    canvas = Canvas(cell_w * len(times), cell_h * 3)
    # back view (character's right on the right), right-side view (forward on the right), top view (forward up)
    views = [
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - 30 + p[1], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h / 2 + 40 - p[1]),
    ]
    for column, t in enumerate(times):
        _, world, _ = motion.pose(time_to_param(t))
        pommel, tip = sword_points(world)
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
    canvas.save(PREVIEW_PATH)
    unreal.log_warning("SLASH preview written to " + PREVIEW_PATH)


def segment_distance(p1, q1, p2, q2):
    """Closest distance between two segments (sampled; good enough for a sanity check)."""
    best = 1e9
    for i in range(21):
        a = lerp(p1, q1, i / 20.0)
        for j in range(11):
            best = min(best, length(sub(a, lerp(p2, q2, j / 10.0))))
    return best


def body_clearance(world):
    pommel, tip = sword_points(world)
    blade_start = lerp(pommel, tip, (POMMEL + 12.0) / (POMMEL + BLADE_TIP))
    worst = (1e9, "")
    for a, b in (("pelvis", "spine_03"), ("spine_03", "neck_01"), ("neck_01", "head"), ("thigh_l", "calf_l"),
                 ("thigh_r", "calf_r"), ("calf_l", "foot_l"), ("calf_r", "foot_r"),
                 ("upperarm_l", "lowerarm_l"), ("lowerarm_l", "hand_l")):
        d = segment_distance(blade_start, tip, world[a][0], world[b][0])
        if d < worst[0]:
            worst = (d, a)
    return worst


# ---------------------------------------------------------------- asset writing

def write_assets(rig, idle_anim, frames):
    eal = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    skeleton = idle_anim.get_skeleton() if hasattr(idle_anim, "get_skeleton") else idle_anim.get_editor_property("skeleton")

    for name in (MONTAGE_NAME, SEQUENCE_NAME):
        if eal.does_asset_exist(OUT_DIR + "/" + name):
            eal.delete_asset(OUT_DIR + "/" + name)

    factory = unreal.AnimSequenceFactory()
    factory.set_editor_property("target_skeleton", skeleton)
    sequence = tools.create_asset(SEQUENCE_NAME, OUT_DIR, unreal.AnimSequence, factory)

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
    controller.set_frame_rate(unreal.FrameRate(FPS, 1), False)
    controller.set_number_of_frames(unreal.FrameNumber(len(frames) - 1), False)
    for bone in rig.bones:
        controller.add_bone_curve(bone, False)
        p, r, s = tracks[bone]
        controller.set_bone_track_keys(bone, p, r, s, False)
    controller.close_bracket(False)

    lib = unreal.AnimationLibrary
    lib.add_animation_notify_track(sequence, "Combat")
    lib.add_animation_notify_event(sequence, "Combat", HIT_TIME, unreal.AnimNotify_DoAttackTrace)
    lib.add_animation_notify_event(sequence, "Combat", COMBO_TIME, unreal.AnimNotify_CheckCombo)
    eal.save_loaded_asset(sequence)

    montage_factory = unreal.AnimMontageFactory()
    montage_factory.set_editor_property("target_skeleton", skeleton)
    montage_factory.set_editor_property("source_animation", sequence)
    montage = tools.create_asset(MONTAGE_NAME, OUT_DIR, unreal.AnimMontage, montage_factory)
    for prop, seconds in (("blend_in", 0.10), ("blend_out", 0.22)):
        try:
            blend = montage.get_editor_property(prop)
            blend.set_editor_property("blend_time", seconds)
            montage.set_editor_property(prop, blend)
        except Exception as error:  # property layout differs between engine versions
            unreal.log_warning("SLASH could not set {}: {}".format(prop, error))
    eal.save_loaded_asset(montage)
    unreal.log_warning("SLASH created {}/{} ({} frames, {:.2f}s) and {} (length {:.2f}s)".format(
        OUT_DIR, SEQUENCE_NAME, len(frames), (len(frames) - 1) / FPS, MONTAGE_NAME, montage.get_play_length()))


def main():
    idle_anim = unreal.load_asset(IDLE_ANIM)
    rig = Rig(idle_anim)
    motion = Motion(rig)
    unreal.log_warning("SLASH idle: swivel={:.0f}deg wrist_bend={:.0f}deg".format(motion.arm.idle_swivel, motion.idle_wrist_bend()))

    # The first pose must reproduce the idle pose (apart from the closed fist)
    local, world, _ = motion.pose(0.0)
    error = max(length(sub(world[b][0], rig.idle_world[b][0])) for b in ("hand_r", "lowerarm_r", "foot_l", "foot_r", "head"))
    unreal.log_warning("SLASH idle reproduction error {:.3f} cm".format(error))

    count = int(round(KEYS[-1]["t"] * FPS))
    frames = []
    worst = (1e9, "", 0.0)
    max_twist = max_bend = 0.0
    previous = -1.0
    for frame_index in range(count + 1):
        t = frame_index / FPS
        u = time_to_param(t)
        if u < previous - 1e-6:
            raise RuntimeError("Time mapping is not monotone at t={:.3f}".format(t))
        previous = u
        local, world, info = motion.pose(u)
        frames.append(local)
        max_twist = max(max_twist, abs(info["twist"]))
        max_bend = max(max_bend, info["bend"])
        clearance = body_clearance(world)
        if clearance[0] < worst[0]:
            worst = (clearance[0], clearance[1], t)
    unreal.log_warning("SLASH closest blade-to-body distance {:.1f} cm (near {}) at t={:.2f}s".format(*worst))
    unreal.log_warning("SLASH max forearm twist {:.0f}deg, max wrist bend {:.0f}deg".format(max_twist, max_bend))

    draw_preview(motion, [0.0, 0.14, 0.27, 0.32, 0.37, 0.41, 0.46, 0.57, 0.80])
    if not PREVIEW_ONLY:
        write_assets(rig, idle_anim, frames)


main()
