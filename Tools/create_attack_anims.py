"""
Generates everything about how the player character carries and swings its weapons:
  /Game/Weapons/Sword/Anims/AS_Stance_SwordShield       combat stance: shield in front, sword ready
  /Game/Weapons/Sword/Anims/AS_SwordSlash               one-handed diagonal slash
  /Game/Weapons/Greatsword/Anims/AS_Stance_Greatsword   combat stance: two-handed guard
  /Game/Weapons/Greatsword/Anims/AS_GreatswordSlash     two-handed diagonal slash
  Tools/mounts.json, Source/OpenWorld/OpenWorldGeneratedMounts.h
                                                        where the weapons sit on the body when put away
Both slashes cut from the upper right to the lower left, in front of the body, and start and end in the stance.
In the combat stance the knees are slightly bent; the game applies that part only while standing.

Everything is solved against the character's collision surface (owlib.BodySurface) and the shapes of the
weapons: nothing may pass through anything (see CLAUDE.md). The script reports the deepest overlap per
animation; Tools/audit_collisions.py re-checks the saved assets, also combined with walking and running.

The motion is authored procedurally:
  - pelvis shift/turn with the feet kept planted (leg IK), torso twist and lean, head kept looking forward,
  - two-bone IK for the arms with an anatomically consistent elbow hinge; the elbow direction is chosen
    per key for small wrist bend / forearm twist and no contact with the body,
  - wrist orientation that keeps the blade edge in the slash plane,
  - the left hand follows the grip of a two-handed sword, or keeps holding the shield,
  - every frame is then pushed out of any remaining overlap, and the corrections are smoothed.

Run (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/create_attack_anims.py -unattended -nosplash -NullRHI

Environment variables:
  SLASH_PREVIEW=1     only write the stick-figure previews (Saved/<name>_Preview.png: back view,
                      right-side view, top view) without touching assets
  SLASH_ONLY=<setup>  only generate this setup ("sword_shield" or "greatsword")
  SLASH_MOUNTS_ONLY=1 only place the put-away weapons (and write the mounts), without the animations

Character space: +Y forward, +Z up, -X is the character's right side.
Sword in hand_r bone space: blade = +Z, flat side normal = Y, fingers = -X.
"""
import json
import math
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from owlib import *  # noqa: E402,F401,F403  (math helpers, Rig, Limb, BodySurface, collision checks, Canvas)

PREVIEW_ONLY = os.environ.get("SLASH_PREVIEW") == "1"
FPS = 60
MARGIN = 3.0    # cm kept between surfaces when resolving contacts; the saved, compressed animation differs from the computed one by up to ~2 cm

# Locomotion the stances are carried over: (animation, number of poses sampled over its length)
LOCOMOTION = [
    ("/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle", 2),
    ("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd", 6),
    ("/Game/Characters/Mannequins/Anims/Unarmed/Jog/MF_Unarmed_Jog_Fwd", 10),
]

# ---------------------------------------------------------------- what to generate

# Slash direction: from the upper right to the lower left. The slash plane contains this and "forward".
SLASH_DIR = norm((0.72, 0.0, -0.69))
PLANE_NORMAL = norm(cross(SLASH_DIR, FWD))


def in_plane(forward, along_slash):
    return norm(add(mul(FWD, forward), mul(SLASH_DIR, along_slash)))


REST = dict(hand=None, blade=None, twist=0.0, lean=0.0, pelvis_yaw=0.0, pelvis=(0.0, 0.0, 0.0))

# The combat stance's body: hips dropped (knees bent, feet where they were) and a slight forward lean.
# Every key's pelvis offset and lean is on top of this.
COMBAT_PELVIS = (0.0, 2.0, -5.0)
COMBAT_LEAN = 5.0

# stance:
#   right        wrist position, blade direction and the normal of the blade's flat side
#   left         "shield": wrist position, direction the shield faces, its up direction
#                "grip":   the hand holds the sword grip `offset` cm from the right hand (negative = toward the pommel)
# attack keys (the first and last are the stance):
#   t            time [s]
#   hand         right wrist target; blade = wanted blade direction. The real blade direction stays in the
#                slash plane at an angle to the forearm that a wrist can hold, as close to it as possible.
#   twist        spine twist to the right [deg]; lean = spine lean forward [deg]
#   pelvis_yaw   pelvis turn to the right [deg]; pelvis = pelvis offset (x: -right/+left, y: forward, z: up) [cm]
# key_speed:     speed of the path parameter at each key (keys per second): slow at the top, fastest through the cut
# hit_time / combo_time are only reported; the character's loadout uses the same values.
SETUPS = {
    "sword_shield": dict(
        loadout="sword_shield", out_dir="/Game/Weapons/Sword/Anims", stance_name="AS_Stance_SwordShield",
        stance=dict(
            # sword at the right side above the hip, point forward and up; clear of the leg even when it lifts in a run
            right=dict(hand=(-31.0, 12.0, 105.0), blade=norm((-0.25, 0.72, 0.64)), flat=(1.0, 0.0, 0.0)),
            # shield held in front of the left chest, high enough to clear the knees in a run
            left=dict(kind="shield", hand=(13.0, 30.0, 128.0), facing=norm((0.22, 0.975, 0.0)), up=UP),
        ),
        # where the shield arm goes while the sword cuts across the front: out to the left side
        open=dict(
            right=dict(hand=(-31.0, 12.0, 105.0), blade=norm((-0.25, 0.72, 0.64)), flat=(1.0, 0.0, 0.0)),
            left=dict(kind="shield", hand=(31.0, 16.0, 111.0), facing=norm((0.96, 0.28, 0.0)), up=UP),
        ),
        # how far the shield arm is opened at each key of the attack (0 = stance, 1 = open)
        open_weights=[0.0, 0.7, 1.0, 1.0, 0.9, 0.0],
        # weapons put away: item -> (bone it hangs on, candidate placements)
        sheathed=dict(loadout="sword_shield_sheathed", items=dict(sword="hip", scabbard="hip", shield="back")),
        attack=dict(
            name="AS_SwordSlash", hit_time=0.38, combo_time=0.66,
            keys=[
                dict(REST, t=0.00),
                # Wind-up: sword raised over the right shoulder, weight back, chest opened to the right
                dict(t=0.27, hand=(-31.0, -5.0, 160.0), blade=in_plane(-0.6, -0.8),
                     twist=21.0, lean=-4.0, pelvis_yaw=9.0, pelvis=(-1.5, -3.0, -1.0)),
                # Impact: arm extended in front of the chest, blade leading forward
                dict(t=0.37, hand=(-4.0, 39.0, 118.0), blade=in_plane(1.0, -0.30),
                     twist=-2.0, lean=6.0, pelvis_yaw=-2.0, pelvis=(1.0, 4.0, -3.0)),
                # End of the cut: hand low in front of the body, blade forward-left-down
                dict(t=0.46, hand=(6.0, 37.0, 108.0), blade=in_plane(0.75, 0.65),
                     twist=-16.0, lean=11.0, pelvis_yaw=-9.0, pelvis=(2.5, 6.0, -4.5)),
                # Follow-through stops short of the shield arm
                dict(t=0.57, hand=(11.0, 33.0, 104.0), blade=in_plane(0.60, 0.80),
                     twist=-19.0, lean=11.0, pelvis_yaw=-10.0, pelvis=(2.5, 6.0, -4.5)),
                dict(REST, t=1.00),
            ],
            key_speed=[0.0, 2.0, 13.0, 7.0, 0.8, 0.0],
        ),
    ),
    "greatsword": dict(
        loadout="greatsword", out_dir="/Game/Weapons/Greatsword/Anims", stance_name="AS_Stance_Greatsword",
        stance=dict(
            # both hands on the grip in front of the chest, blade up and a little forward ("high port");
            # the pommel stays above the thighs even when they lift in a run
            right=dict(hand=(-5.0, 36.0, 125.0), blade=norm((-0.12, 0.48, 0.87)), flat=(1.0, 0.0, 0.0)),
            left=dict(kind="grip", offset=-13.0),
        ),
        sheathed=dict(loadout="greatsword_sheathed", items=dict(greatsword="back_long")),
        attack=dict(
            name="AS_GreatswordSlash", hit_time=0.47, combo_time=0.84,
            keys=[
                dict(REST, t=0.00),
                # Wind-up: both hands at the right shoulder, blade back over it, hips and chest turned right
                dict(t=0.34, hand=(-20.0, 2.0, 157.0), blade=in_plane(-0.6, -0.8),
                     twist=24.0, lean=-5.0, pelvis_yaw=13.0, pelvis=(-2.0, -4.0, -1.5)),
                # Impact: both arms pushed forward in front of the chest
                dict(t=0.46, hand=(-3.0, 38.0, 122.0), blade=in_plane(1.0, -0.30),
                     twist=-4.0, lean=8.0, pelvis_yaw=-3.0, pelvis=(1.0, 5.0, -4.0)),
                # End of the cut: hands in front of the left hip, weight on the front leg
                dict(t=0.56, hand=(8.0, 37.0, 104.0), blade=in_plane(0.75, 0.65),
                     twist=-22.0, lean=10.0, pelvis_yaw=-13.0, pelvis=(3.0, 7.0, -6.0)),
                # Follow-through
                dict(t=0.69, hand=(14.0, 33.0, 100.0), blade=in_plane(0.6, 0.8),
                     twist=-27.0, lean=10.0, pelvis_yaw=-15.0, pelvis=(3.0, 7.0, -6.0)),
                dict(REST, t=1.30),
            ],
            key_speed=[0.0, 1.5, 11.0, 6.0, 0.7, 0.0],
        ),
    ),
}

# Angles between forearm and blade a wrist can hold in a hammer grip (90 = neutral wrist)
WRIST_ANGLES = [58.0, 66.0, 74.0, 82.0, 90.0, 98.0, 106.0]
SPINE = ["spine_01", "spine_02", "spine_03", "spine_04", "spine_05"]
NECK = ["neck_01", "neck_02", "head"]
FINGER_CURL = {"01": 62.0, "02": 88.0, "03": 55.0}
FINGERS = ["index", "middle", "ring", "pinky"]
ARM_BONES = ["upperarm", "lowerarm", "hand"]


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def weapon_points(world, loadout):
    """The held weapons as small spheres [(name, centre, radius)], for contact resolution."""
    points = []
    capsules, _ = equipment_shapes(world, loadout)
    for name, side, segments, radius in capsules:
        for a, b in segments:
            steps = max(2, int(length(sub(b, a)) / 6.0))
            for k in range(steps + 1):
                points.append((name, lerp(a, b, k / steps), radius))
    return points


class Motion:
    def __init__(self, rig, surface, setup, locomotion):
        self.rig = rig
        self.surface = surface
        self.setup = setup
        self.locomotion = locomotion     # local poses the stance is carried over
        self.carried_where = ""
        self.loadout = setup["loadout"]
        self.keys = setup["attack"]["keys"]
        self.two_handed = setup["stance"]["left"]["kind"] == "grip"
        self.arm = Limb(rig, "upperarm_r", "lowerarm_r", "hand_r", 0.985)
        self.arm_l = Limb(rig, "upperarm_l", "lowerarm_l", "hand_l", 0.985)
        self.legs = [Limb(rig, "thigh_{}".format(s), "calf_{}".format(s), "foot_{}".format(s), 0.9995) for s in "lr"]
        # Palm normal in hand space: the +/-Y axis that faces the body in the idle pose
        self.palm = {}
        for side in "lr":
            pos, rot = rig.idle_world["hand_" + side]
            inward = (-1.0 if pos[0] > 0 else 1.0, 0.0, 0.0)
            self.palm[side] = (0.0, 1.0, 0.0) if dot(qrot(rot, (0.0, 1.0, 0.0)), inward) > 0 else (0.0, -1.0, 0.0)
        self.arm_bones_l = [b for b in rig.bones if rig.ancestor_in(b, {"upperarm_l"})]
        self.arm_bones = [b for b in rig.bones if rig.ancestor_in(b, {"upperarm_l", "upperarm_r"})]

        # stance: right hand dict(hand, pole, rot); left dict(pole_l, roll) when it grips the same weapon
        self.stance_local, self.stance = self.build_hold(setup["stance"], setup["stance_name"])
        # the shield arm's second pose, used while the sword cuts across the front
        self.open_local = self.build_hold(setup["open"], setup["stance_name"] + " (shield open)")[0] if "open" in setup else None
        self.key_hands = None
        self.key_poles = None
        self.key_rolls = None
        self.key_poles_l = None
        self.plan()
        if self.two_handed:
            self.plan_left()

    def time_to_param(self, t):
        """Cubic Hermite mapping time -> key parameter with the speeds in key_speed."""
        keys, speed = self.keys, self.setup["attack"]["key_speed"]
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

    def posed_body(self, twist=0.0, lean=0.0, pelvis_yaw=0.0, pelvis=(0.0, 0.0, 0.0)):
        """The combat stance's body (knees bent, slight lean, closed fists) moved by the given pelvis and
        torso values. Arms are not posed yet."""
        local = dict(self.rig.base)
        self.apply_fist(local, "r")
        self.apply_fist(local, "l")
        self.apply_pelvis(local, pelvis_yaw, add(COMBAT_PELVIS, pelvis))
        self.apply_torso(local, twist, COMBAT_LEAN + lean, twist + pelvis_yaw)
        return local

    def body_pose(self, u):
        """The body at path parameter u of the attack."""
        keys = self.keys
        return self.posed_body(catmull([k["twist"] for k in keys], u, combine_scalar),
                               catmull([k["lean"] for k in keys], u, combine_scalar),
                               catmull([k["pelvis_yaw"] for k in keys], u, combine_scalar),
                               catmull([k["pelvis"] for k in keys], u, combine_vec))

    # ---- contacts

    def arm_contact(self, world, side, with_hand=True):
        """Deepest overlap of an arm with the torso, head and legs (cm, > 0 = inside)."""
        lower = ["lowerarm_" + side] + (["hand_" + side] if with_hand else [])
        body = self.surface.place(world, TORSO + LEGS)
        depth = deepest(self.surface.place(world, lower), body)[0]
        upper = deepest(self.surface.place(world, ["upperarm_" + side]),
                        self.surface.place(world, ["pelvis", "spine_01", "spine_02", "head"] + LEGS))[0]
        return max(depth, upper)

    def carried_contact(self, local, sides):
        """Deepest overlap of the given arms (and what they hold) when this pose's arms are carried over
        standing, walking and running. sides: "r", "l" or "lr"."""
        gripping = self.two_handed
        worst = -1e9
        for base in self.locomotion:
            pose = dict(base)
            for bone in self.arm_bones:
                pose[bone] = local[bone]
            for label, (depth, where) in measure(self.surface, self.rig.fk(pose), self.loadout, gripping).items():
                mine = ("r" in sides and ("_r " in label or "sword" in label)) or \
                       ("l" in sides and ("_l " in label or label.startswith("shield")))
                if mine and depth > worst:
                    worst = depth
                    self.carried_where = "{} ({})".format(label, where)
        return worst

    def contact_cost(self, depth):
        return (25.0 * max(0.0, depth + MARGIN)) ** 2

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

    def best_right_arm(self, body, hand, blade_options, previous_pole, label, carried=False):
        """Elbow direction and hand rotation for a wrist target: small wrist bend and forearm twist,
        blade as wanted, and no contact with the body. blade_options(forearm) -> [(blade, flat normal, penalty)]."""
        rig = self.rig
        shoulder = rig.fk(body)["upperarm_r"][0]
        direction = norm(sub(hand, shoulder))
        best = None
        for swivel in range(-180, 180, 4):
            pole = pole_from_swivel(direction, float(swivel))
            local = dict(body)
            _, elbow = self.arm.solve(rig, local, hand, pole=pole)
            world = rig.fk(local)
            forearm = norm(sub(world["hand_r"][0], world["lowerarm_r"][0]))
            elbow_cost = (0.2 * angle_between(pole, previous_pole)) ** 2 if previous_pole else 0.0
            elbow_cost += (8.0 * max(0.0, elbow[2] - shoulder[2] - 6.0)) ** 2     # elbow far above the shoulder
            elbow_cost += self.contact_cost(self.arm_contact(world, "r"))
            for blade, flat, penalty in blade_options(forearm):
                rot, bend = self.hand_rotation(blade, flat, forearm)
                trial = dict(local)
                rig.set_world_rot(trial, world, "hand_r", rot)
                twist = self.forearm_twist(trial)
                cost = elbow_cost + bend ** 2 + (0.45 * twist) ** 2 + penalty
                if carried:
                    cost += self.contact_cost(self.carried_contact(trial, "r"))
                cost += (4.0 * max(0.0, abs(twist) - 95.0)) ** 2     # beyond what a forearm can turn
                cost += (4.0 * max(0.0, bend - 55.0)) ** 2           # beyond what a wrist can bend
                if best is None or cost < best[0]:
                    # Keep the hand rotation relative to the forearm: the wrist then moves smoothly between keys
                    best = (cost, pole, trial["hand_r"][1], bend, twist, elbow)
        _, pole, rot, bend, twist, elbow = best
        unreal.log_warning("SLASH {}: R elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg forearm_twist={:.0f}deg".format(
            label, elbow[0], elbow[1], elbow[2], bend, twist))
        return pole, rot

    def left_hand_goal(self, world, roll):
        """Wrist position and rotation of hand_l gripping the handle below the right hand.
        roll = rotation of the left hand around the handle relative to the right hand [deg]."""
        pos, rot = world["hand_r"]
        socket_r = qmul(rot, SOCKET_ROT["r"])
        axis = qrot(socket_r, (0.0, 0.0, 1.0))
        point = add(add(pos, qrot(rot, GRIP_OFFSET["r"])), mul(axis, self.setup["stance"]["left"]["offset"]))
        x = qrot(qaxis(axis, roll), qrot(socket_r, (1.0, 0.0, 0.0)))
        socket_l = qfrom_axes(x, cross(axis, x), axis)
        hand_rot = qnorm(qmul(socket_l, qconj(SOCKET_ROT["l"])))
        return sub(point, qrot(hand_rot, GRIP_OFFSET["l"])), hand_rot

    def left_grip_options(self, local, world, roll):
        """(cost, pole, bend, twist, miss, elbow) for every left elbow direction, with the left hand on the grip."""
        rig = self.rig
        shoulder = world["upperarm_l"][0]
        wrist, hand_rot = self.left_hand_goal(world, float(roll))
        direction = norm(sub(wrist, shoulder))
        result = []
        for swivel in range(-180, 180, 6):
            pole = pole_from_swivel(direction, float(swivel))
            trial = dict(local)
            reached, elbow = self.arm_l.solve(rig, trial, wrist, pole=pole)
            trial_world = rig.fk(trial)
            rig.set_world_rot(trial, trial_world, "hand_l", hand_rot)
            bend = angle_between(qrot(hand_rot, FINGER_AXIS["l"]), norm(sub(reached, elbow)))
            twist = self.forearm_twist(trial, "l")
            miss = length(sub(reached, wrist))
            cost = bend ** 2 + (0.45 * twist) ** 2 + (25.0 * miss) ** 2
            cost += (2.0 * max(0.0, abs(twist) - 95.0)) ** 2                 # beyond what a forearm can turn
            cost += (2.0 * max(0.0, bend - 55.0)) ** 2                       # beyond what a wrist can bend
            cost += (8.0 * max(0.0, elbow[2] - shoulder[2] - 6.0)) ** 2      # elbow far above the shoulder
            cost += (4.0 * max(0.0, elbow[0] - shoulder[0] - 14.0)) ** 2     # elbow winged far out to the left
            contact = max(self.arm_contact(trial_world, "l", with_hand=False),
                          deepest(self.surface.place(trial_world, ["lowerarm_l"]),
                                  self.surface.place(trial_world, ["upperarm_r", "lowerarm_r"]))[0])
            cost += self.contact_cost(contact)
            result.append((cost, pole, bend, twist, miss, elbow))
        return result

    def build_hold(self, spec, label):
        """A pose the weapons are held in: the combat stance's body, arms holding the weapons clear of the
        body in every locomotion state. Returns (local pose, dict with the arm solution)."""
        rig = self.rig
        local = self.posed_body()

        right = spec["right"]
        pole, rot = self.best_right_arm(local, right["hand"], lambda forearm: [(right["blade"], right["flat"], 0.0)],
                                        None, label, carried=True)
        self.arm.solve(rig, local, right["hand"], pole=pole)
        local["hand_r"] = (local["hand_r"][0], rot)
        self.spread_forearm_twist(local, "r")
        hold = dict(hand=right["hand"], pole=pole, rot=rot)

        left = spec["left"]
        world = rig.fk(local)
        if left["kind"] == "shield":
            # Socket axes: X = the way the shield faces (back of the hand), Z = up (thumb side)
            facing = norm(left["facing"])
            up = norm(reject(left["up"], facing))
            hand_rot = qnorm(qmul(qfrom_axes(facing, cross(up, facing), up), qconj(SOCKET_ROT["l"])))
            shoulder = world["upperarm_l"][0]
            direction = norm(sub(left["hand"], shoulder))
            best = None
            for swivel in range(-180, 180, 4):
                trial = dict(local)
                reached, elbow = self.arm_l.solve(rig, trial, left["hand"], pole=pole_from_swivel(direction, float(swivel)))
                trial_world = rig.fk(trial)
                rig.set_world_rot(trial, trial_world, "hand_l", hand_rot)
                trial_world = rig.fk(trial)
                bend = self.wrist_bend(trial_world, "l")
                twist = self.forearm_twist(trial, "l")
                self.spread_forearm_twist(trial, "l")
                contact = self.carried_contact(trial, "l")
                cost = bend ** 2 + (0.45 * twist) ** 2 + self.contact_cost(contact) + (8.0 * max(0.0, elbow[2] - shoulder[2])) ** 2
                if best is None or cost < best[0]:
                    best = (cost, trial, bend, twist, contact, elbow)
            _, local, bend, twist, contact, elbow = best
            self.spread_forearm_twist(local, "l")
            unreal.log_warning("SLASH {}: L (shield) elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg forearm_twist={:.0f}deg "
                               "closest to body {:.1f} cm".format(label, elbow[0], elbow[1], elbow[2], bend, twist, -contact))
        else:
            shortlist = []
            for roll in range(-180, 180, 15):
                for option in self.left_grip_options(local, world, roll):
                    shortlist.append((option, roll))
            shortlist.sort(key=lambda item: item[0][0])
            best = None
            for option, roll in shortlist[:16]:
                trial = dict(local)
                wrist, hand_rot = self.left_hand_goal(world, float(roll))
                self.arm_l.solve(rig, trial, wrist, pole=option[1])
                rig.set_world_rot(trial, rig.fk(trial), "hand_l", hand_rot)
                self.spread_forearm_twist(trial, "l")
                cost = option[0] + self.contact_cost(self.carried_contact(trial, "lr"))
                if best is None or cost < best[0]:
                    best = (cost, option, roll, trial)
            _, (_, pole_l, bend, twist, miss, elbow), roll, local = best
            hold.update(pole_l=pole_l, roll=float(roll))
            unreal.log_warning("SLASH {}: L (grip) roll={}deg elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg "
                               "forearm_twist={:.0f}deg miss={:.1f}cm".format(label, roll, elbow[0], elbow[1], elbow[2], bend, twist, miss))
        return local, hold

    def plan(self):
        """Chooses the right elbow direction and hand rotation at every key of the attack."""
        hands, poles = [], []
        previous = self.stance["pole"]
        for index, key in enumerate(self.keys):
            if key["blade"] is None:
                hands.append(self.stance["rot"])
                poles.append(self.stance["pole"])
                previous = self.stance["pole"]
                continue

            def blade_options(forearm, wanted=key["blade"]):
                options = []
                for wrist_angle in WRIST_ANGLES:
                    for blade in self.blades_in_plane(forearm, wrist_angle):
                        options.append((blade, PLANE_NORMAL, angle_between(blade, wanted) ** 2))
                return options

            pole, rot = self.best_right_arm(self.body_pose(float(index)), key["hand"], blade_options, previous,
                                            "{} key {} t={:.2f}".format(self.setup["attack"]["name"], index, key["t"]))
            hands.append(rot)
            poles.append(pole)
            previous = pole
        for index in range(1, len(hands)):
            if sum(a * b for a, b in zip(hands[index - 1], hands[index])) < 0:
                hands[index] = tuple(-c for c in hands[index])
        self.key_hands, self.key_poles = hands, poles

    def plan_left(self):
        """Left elbow direction at every key, and how the left hand turns around the handle. The grip stays
        close to the stance's (hands do not re-grip mid-swing) but may turn a little, as a real grip does."""
        rolls, poles = [], []
        previous = self.stance["pole_l"]
        for index, key in enumerate(self.keys):
            if key["blade"] is None:
                rolls.append(self.stance["roll"])
                poles.append(self.stance["pole_l"])
                previous = self.stance["pole_l"]
                continue
            local, world, _ = self.pose(float(index), left=False)
            options = []
            for delta in (-45, -30, -15, 0, 15, 30, 45):
                roll = self.stance["roll"] + delta
                for c in self.left_grip_options(local, world, roll):
                    options.append((c[0] + (0.4 * delta) ** 2 + (0.3 * angle_between(c[1], previous)) ** 2, roll) + c[1:])
            _, roll, pole, bend, twist, miss, elbow = min(options, key=lambda c: c[0])
            unreal.log_warning("SLASH {} key {} t={:.2f}: L roll={:.0f}deg elbow=({:.0f},{:.0f},{:.0f}) wrist_bend={:.0f}deg "
                               "forearm_twist={:.0f}deg miss={:.1f}cm".format(
                                   self.setup["attack"]["name"], index, key["t"], roll, elbow[0], elbow[1], elbow[2], bend, twist, miss))
            rolls.append(float(roll))
            poles.append(pole)
            previous = pole
        self.key_rolls, self.key_poles_l = rolls, poles

    def pose(self, u, left=True, offset=(0.0, 0.0, 0.0), left_pole_override=None):
        """Full local pose at path parameter u (0 .. len(keys)-1). `offset` moves the right wrist target.
        left_pole_override: (elbow direction, turn around the handle) for a two-handed grip.
        Returns (local, world, info)."""
        rig, keys = self.rig, self.keys
        local = self.body_pose(u)
        positions = [k["hand"] if k["hand"] else self.stance["hand"] for k in keys]
        target = add(catmull(positions, u, combine_vec), offset)
        self.arm.solve(rig, local, target, pole=norm(catmull(self.key_poles, u, combine_vec)))

        i = max(0, min(len(keys) - 2, int(math.floor(u))))
        local["hand_r"] = (local["hand_r"][0], qslerp(self.key_hands[i], self.key_hands[i + 1], u - i))
        twist = self.spread_forearm_twist(local, "r")
        world = rig.fk(local)
        info = dict(twist=twist, bend=self.wrist_bend(world, "r"), left_miss=0.0, left_bend=0.0, left_twist=0.0)

        if left and self.two_handed:
            pole, roll = left_pole_override or (norm(catmull(self.key_poles_l, u, combine_vec)), catmull(self.key_rolls, u, combine_scalar))
            wrist, hand_rot = self.left_hand_goal(world, roll)
            reached, _ = self.arm_l.solve(rig, local, wrist, pole=pole)
            world = rig.fk(local)
            rig.set_world_rot(local, world, "hand_l", hand_rot)
            info["left_twist"] = self.spread_forearm_twist(local, "l")
            world = rig.fk(local)
            info["left_bend"] = self.wrist_bend(world, "l")
            info["left_miss"] = length(sub(reached, wrist))
        elif left:
            # The shield arm keeps its stance relative to the chest, and swings out of the sword's way during the cut
            weight = 0.0
            if self.open_local is not None:
                weight = max(0.0, min(1.0, catmull(self.setup["open_weights"], u, combine_scalar)))
            for bone in self.arm_bones_l:
                pos, rot = self.stance_local[bone]
                if weight > 0.0:
                    rot = qnorm(qslerp(rot, self.open_local[bone][1], weight))
                local[bone] = (pos, rot)
            world = rig.fk(local)

        # IK helper bones follow the hands
        for ik_bone, source in (("ik_hand_gun", "hand_r"), ("ik_hand_r", "hand_r"), ("ik_hand_l", "hand_l")):
            if ik_bone in local:
                rig.set_world(local, world, ik_bone, world[source][0], world[source][1])
                world = rig.fk(local)
        return local, world, info

    # ---- contact resolution

    def right_side_push(self, world):
        """Deepest overlap of the right forearm, hand and the weapon with everything they must not touch.
        Returns (depth incl. margin, direction to move the right wrist to get out)."""
        surface = self.surface
        movers = [(b, c, r) for b, c, r in surface.place(world, ["lowerarm_r", "hand_r"])]
        movers += weapon_points(world, self.loadout)
        if self.two_handed:
            # the left hand is on the same grip, so moving the right wrist moves it too
            movers += surface.place(world, ["lowerarm_l", "hand_l"])
        obstacles = surface.place(world, TORSO + LEGS)
        if not self.two_handed:
            obstacles += surface.place(world, ["upperarm_l", "lowerarm_l", "hand_l"])
        best = (0.0, None)
        for name, cm, rm in movers:
            for bone, co, ro in obstacles:
                d = sub(cm, co)
                dist = length(d)
                depth = rm + ro + MARGIN - dist
                if depth > best[0]:
                    best = (depth, norm(d) if dist > 1e-6 else FWD)
        # The weapon against the shield
        _, discs = equipment_shapes(world, self.loadout)
        for _, _, centre, normal, radius, half_thickness in discs:
            for name, cm, rm in weapon_points(world, self.loadout):
                depth = rm + MARGIN - point_disc_distance(cm, centre, normal, radius, half_thickness)
                if depth > best[0]:
                    side = 1.0 if dot(sub(cm, centre), normal) >= 0 else -1.0
                    best = (depth, mul(normal, side))
        return best

    def pick_left_pole(self, u, offset, near):
        """Left elbow direction and turn of the hand around the handle for this frame: comfortable, clear of
        the body, and close to `near` (the previous frame's (pole, roll), or None)."""
        base_local, base_world, _ = self.pose(u, left=False, offset=offset)
        planned = catmull(self.key_rolls, u, combine_scalar)
        near_pole = near[0] if near else norm(catmull(self.key_poles_l, u, combine_vec))
        near_roll = near[1] if near else planned
        options = []
        for delta in (-30.0, -15.0, 0.0, 15.0, 30.0):
            roll = planned + delta
            for c in self.left_grip_options(base_local, base_world, roll):
                options.append((c[0] + (0.6 * angle_between(c[1], near_pole)) ** 2 + (0.8 * (roll - near_roll)) ** 2 + (0.3 * delta) ** 2,
                                (c[1], roll)))
        return min(options, key=lambda c: c[0])[1]

    def resolved_pose(self, u, offset, previous_left_pole=None):
        """Pose at u, moved out of contact: the right wrist target is pushed away from what it (or anything
        attached to it) touches; for a two-handed grip the left elbow is chosen per frame.
        Returns (local, world, info, final offset, left pole)."""
        left_pole = None
        if self.two_handed:
            left_pole = self.pick_left_pole(u, offset, previous_left_pole)
        local, world, info = self.pose(u, offset=offset, left_pole_override=left_pole)
        for _ in range(14):
            depth, direction = self.right_side_push(world)
            if direction is None:
                break
            offset = add(offset, mul(direction, min(depth, 4.0)))
            local, world, info = self.pose(u, offset=offset, left_pole_override=left_pole)
        if self.two_handed and self.arm_contact(world, "l", with_hand=False) > -MARGIN:
            left_pole = self.pick_left_pole(u, offset, left_pole)
            local, world, info = self.pose(u, offset=offset, left_pole_override=left_pole)
        return local, world, info, offset, left_pole

    def sword_points(self, world):
        pos, rot = world["hand_r"]
        grip = add(pos, qrot(rot, GRIP_OFFSET["r"]))
        axis = qrot(rot, (0.0, 0.0, 1.0))
        blade = [p for p in EQUIPMENT[LOADOUTS[self.loadout]["items"][0]]["parts"] if p["kind"] == "blade"]
        low = min(p["z0"] for p in blade)
        high = max(p["z1"] for p in blade)
        return add(grip, mul(axis, min(low, -9.0))), add(grip, mul(axis, high))


# ---------------------------------------------------------------- preview image

BODY_LINES = [
    (["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"], (90, 90, 90)),
    (["pelvis", "thigh_l", "calf_l", "foot_l", "ball_l"], (160, 160, 160)),
    (["pelvis", "thigh_r", "calf_r", "foot_r", "ball_r"], (110, 110, 110)),
    (["spine_05", "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l"], (60, 160, 60)),
    (["spine_05", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r"], (40, 90, 220)),
]


def draw_preview(motion, worlds, path):
    cell_w, cell_h = 230, 270
    canvas = Canvas(cell_w * len(worlds), cell_h * 3)
    # back view (character's right on the right), right-side view (forward on the right), top view (forward up)
    views = [
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - 30 + p[1], oy + cell_h - 15 - p[2]),
        lambda p, ox, oy: (ox + cell_w / 2 - p[0], oy + cell_h / 2 + 40 - p[1]),
    ]
    for column, world in enumerate(worlds):
        pommel, tip = motion.sword_points(world)
        _, discs = equipment_shapes(world, motion.loadout)
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
            for _, _, centre, normal, radius, _ in discs:
                e1 = norm(reject(UP, normal))
                e2 = cross(normal, e1)
                for ang in range(0, 360, 6):
                    rim = add(centre, add(mul(e1, radius * math.cos(math.radians(ang))), mul(e2, radius * math.sin(math.radians(ang)))))
                    canvas.dot(*view(rim, ox, oy), (200, 130, 20), 0)
    canvas.save(path)
    unreal.log_warning("SLASH preview written to " + path)


# ---------------------------------------------------------------- asset writing

def write_sequence(rig, out_dir, name, frames):
    eal = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    skeleton = rig.idle_anim.get_skeleton() if hasattr(rig.idle_anim, "get_skeleton") else rig.idle_anim.get_editor_property("skeleton")
    path = out_dir + "/" + name
    # An existing asset is rewritten in place: other assets may reference it, so it can not be deleted.
    existing = eal.does_asset_exist(path)
    if existing:
        sequence = unreal.load_asset(path)
    else:
        factory = unreal.AnimSequenceFactory()
        factory.set_editor_property("target_skeleton", skeleton)
        sequence = tools.create_asset(name, out_dir, unreal.AnimSequence, factory)

    tracks = {bone: ([], [], []) for bone in rig.bones}
    for local in frames:
        for bone in rig.bones:
            pos, rot = local[bone]
            p, r, s = tracks[bone]
            p.append(unreal.Vector(*mul(pos, rig.write_scale.get(bone, 1.0))))
            r.append(unreal.Quat(rot[0], rot[1], rot[2], rot[3]))
            s.append(unreal.Vector(*rig.scale[bone]))

    controller = sequence.controller
    controller.open_bracket(unreal.Text("Generate animation"), False)
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
    unreal.log_warning("SLASH created {} ({} frames, {:.2f}s)".format(path, len(frames), sequence.get_play_length()))


def smooth(values, passes=3):
    """Binomial smoothing of a list of vectors; the ends stay fixed."""
    for _ in range(passes):
        out = list(values)
        for i in range(1, len(values) - 1):
            out[i] = add(add(mul(values[i - 1], 0.25), mul(values[i], 0.5)), mul(values[i + 1], 0.25))
        values = out
    return values


def report_contacts(label, motion, worlds, times, gripping):
    worst = {}
    for world, t in zip(worlds, times):
        for check, (depth, where) in measure(motion.surface, world, motion.loadout, gripping).items():
            if check not in worst or depth > worst[check][0]:
                worst[check] = (depth, where, t)
    bad = sorted(((d, c, w, t) for c, (d, w, t) in worst.items() if d > 0.5), reverse=True)
    if not bad:
        unreal.log_warning("SLASH {}: no surface passes through another (closest {:.1f} cm)".format(label, -max(d for d, _, _ in worst.values())))
    for depth, check, where, t in bad:
        unreal.log_warning("SLASH {}: PENETRATION {:.1f} cm  {} ({}) at t={:.2f}s".format(label, depth, check, where, t))
    return len(bad)


def generate(rig, surface, setup, locomotion):
    motion = Motion(rig, surface, setup, locomotion)
    attack = setup["attack"]
    name = attack["name"]
    gripping = motion.two_handed

    stance_world = rig.fk(motion.stance_local)
    failures = report_contacts(setup["stance_name"], motion, [stance_world], [0.0], gripping)
    carried = motion.carried_contact(motion.stance_local, "lr")
    unreal.log_warning("SLASH {}: carried over standing, walking and running: {} - {}".format(
        setup["stance_name"], "clear, closest {:.1f} cm".format(-carried) if carried <= 0 else "PENETRATION {:.1f} cm".format(carried),
        motion.carried_where))
    failures += 1 if carried > 0.5 else 0

    duration = attack["keys"][-1]["t"]
    if abs(duration * 30.0 - round(duration * 30.0)) > 1e-6:
        # Unreal resamples animations to 30 fps when compressing; other lengths crash the compression.
        raise RuntimeError("{}: the length {}s must be a multiple of 1/30 s".format(name, duration))
    count = int(round(duration * FPS))
    params = [motion.time_to_param(i / FPS) for i in range(count + 1)]
    if any(b < a - 1e-6 for a, b in zip(params, params[1:])):
        raise RuntimeError(name + ": time mapping is not monotone")

    # Pass 1: resolve contacts frame by frame. Pass 2: smooth the corrections, then resolve what is left.
    # The first and last frame are the stance itself and are never moved.
    last = len(params) - 1
    offsets, pole = [], None
    for index, u in enumerate(params):
        if index in (0, last):
            offsets.append((0.0, 0.0, 0.0))
            pole = None
            continue
        result = motion.resolved_pose(u, (0.0, 0.0, 0.0), pole)
        offsets.append(result[3])
        pole = result[4]
    largest = max(length(o) for o in offsets)
    offsets = smooth(offsets)
    frames, worlds = [], []
    peak = dict(twist=0.0, bend=0.0, left_miss=0.0, left_bend=0.0, left_twist=0.0)
    pole = None
    for index, (u, offset) in enumerate(zip(params, offsets)):
        if index in (0, last):
            local, world, info = motion.pose(u)
            pole = None
        else:
            local, world, info, _, pole = motion.resolved_pose(u, offset, pole)
        frames.append(local)
        worlds.append(world)
        for k in peak:
            peak[k] = max(peak[k], abs(info[k]))

    start_error = max(length(sub(worlds[0][b][0], stance_world[b][0])) for b in ("hand_r", "hand_l", "lowerarm_r", "foot_l", "head"))
    unreal.log_warning("SLASH {}: starts {:.2f} cm from the stance; largest contact correction {:.1f} cm".format(name, start_error, largest))
    unreal.log_warning("SLASH {} right hand: max forearm twist {:.0f}deg, max wrist bend {:.0f}deg".format(name, peak["twist"], peak["bend"]))
    if gripping:
        unreal.log_warning("SLASH {} left hand: max forearm twist {:.0f}deg, max wrist bend {:.0f}deg, max distance from the grip {:.1f} cm".format(
            name, peak["left_twist"], peak["left_bend"], peak["left_miss"]))
    failures += report_contacts(name, motion, worlds, [i / FPS for i in range(count + 1)], gripping)
    unreal.log_warning("SLASH {}: hit_time={:.2f}s combo_time={:.2f}s".format(name, attack["hit_time"], attack["combo_time"]))

    k = [key["t"] for key in attack["keys"]]
    times = [0.0, k[1] * 0.5, k[1], (k[1] + k[2]) * 0.5, k[2], (k[2] + k[3]) * 0.5, k[3], k[4], (k[4] + k[5]) * 0.5]
    draw_preview(motion, [worlds[min(count, int(round(t * FPS)))] for t in times],
                 os.path.join(unreal.Paths.project_saved_dir(), name + "_Preview.png"))
    if not PREVIEW_ONLY:
        write_sequence(rig, setup["out_dir"], setup["stance_name"], [motion.stance_local, motion.stance_local, motion.stance_local])
        write_sequence(rig, setup["out_dir"], name, frames)
    return failures


# ---------------------------------------------------------------- weapons put away

def mount_candidates(place):
    """Grip frames (origin, rotation, tidiness cost) to try for an item hung on the body, in character space.
    The rotation's Z is the blade direction (or the shield's up), X the item's thin side / the shield's face."""
    def frame_from(z, x):
        z = norm(z)
        x = norm(reject(x, z))
        return qfrom_axes(x, cross(z, x), z)

    if place == "hip":
        # sword at the left hip: hilt up, blade down and back along the leg, hanging a little off the body
        for x in (24.0, 27.0, 30.0, 33.0, 36.0):
            for y in (-16.0, -10.0, -4.0, 2.0, 8.0):
                for z in (94.0, 98.0, 102.0, 106.0):
                    for tilt in (10.0, 20.0, 30.0, 40.0):
                        for splay in (0.0, 8.0, 16.0):
                            t, sp = math.radians(tilt), math.radians(splay)
                            blade = (math.sin(sp), -math.sin(t) * math.cos(sp), -math.cos(t) * math.cos(sp))
                            tidy = (2.0 * (x - 24.0)) ** 2 + (0.5 * (tilt - 20.0)) ** 2 + (0.7 * splay) ** 2 + (z - 102.0) ** 2
                            yield (x, y, z), frame_from(blade, (1.0, 0.0, 0.0)), tidy
    elif place == "back":
        # shield on the back, face outward
        # (the running arms swing their elbows far behind the back at chest height, so low positions are tried too)
        for z in (98.0, 104.0, 110.0, 116.0, 122.0, 128.0, 134.0, 140.0, 146.0, 152.0, 158.0):
            for y in (-14.0, -16.0, -18.0, -20.0, -22.0, -24.0, -26.0):
                for tilt in (-15.0, 0.0, 15.0):
                    # tilt leans the top of the shield toward (+) or away from (-) the body
                    t = math.radians(tilt)
                    up = (0.0, math.sin(t), math.cos(t))
                    tidy = (3.0 * (abs(y) - 12.0)) ** 2 + (0.5 * (z - 138.0)) ** 2 + (0.5 * tilt) ** 2
                    yield (0.0, y, z), frame_from(up, (0.0, -1.0, 0.0)), tidy
    elif place == "back_long":
        # two-handed sword across the back: hilt over the right shoulder, blade down toward the left
        for x in (-24.0, -19.0, -14.0, -9.0, -4.0, 0.0):
            for y in (-13.0, -16.0, -19.0, -22.0):
                for z in (152.0, 160.0, 168.0, 176.0):
                    for across in (0.0, 8.0, 16.0, 24.0):
                        for back in (0.0, 6.0):
                            a, b = math.radians(across), math.radians(back)
                            blade = (math.sin(a), -math.sin(b), -math.cos(a) * math.cos(b))
                            tidy = (3.0 * (abs(y) - 13.0)) ** 2 + (0.5 * (across - 14.0)) ** 2 + (0.3 * (z - 160.0)) ** 2
                            yield (x, y, z), frame_from(blade, (0.0, -1.0, 0.0)), tidy


MOUNT_BONE = {"hip": "pelvis", "back": "spine_04", "back_long": "spine_04"}


def place_sheathed(rig, surface, setup, coarse, every_frame):
    """Finds where each item of the setup sits on the body when put away: close to the body, and clear of
    it (and of the swinging arms and legs) while standing, walking and running.
    Candidates are ranked on the `coarse` poses, then the best ones are checked on `every_frame`.
    Returns ({item: (bone, position, rotation)} in the bone's space, number of penetrations left)."""
    sheathed = setup["sheathed"]
    damping = SHEATHED_ARM_DAMPING.get(sheathed["loadout"], 0.0)

    def placed(poses):
        worlds = [rig.fk(damp_arms(rig, pose, damping)) for pose in poses]
        return worlds, [surface.place(world) for world in worlds]

    coarse_worlds, coarse_bodies = placed(coarse)
    worlds, bodies = placed(every_frame)

    def deepest_of(trial, some_worlds, some_bodies):
        depth, where = -1e9, ""
        for world, body in zip(some_worlds, some_bodies):
            capsules, discs = equipment_shapes(world, "_mount", trial)
            for _, _, segments, radius in capsules:
                found = deepest_capsule(segments, radius, body)
                if found[0] > depth:
                    depth, where = found
            for _, _, centre, normal, radius, half_thickness in discs:
                found = deepest_disc(centre, normal, radius, half_thickness, body)
                if found[0] > depth:
                    depth, where = found
        return depth, where

    def cost_of(tidy, depth):
        return tidy + (40.0 * max(0.0, depth + 1.5)) ** 2

    mounts = {}
    solved = {}
    for item, place in sheathed["items"].items():
        if place in solved:
            mounts[item] = solved[place]     # the scabbard shares the sword's mount
            continue
        bone = MOUNT_BONE[place]
        bone_pos, bone_rot = rig.idle_world[bone]
        LOADOUTS["_mount"] = dict(items=[i for i, pl in sheathed["items"].items() if pl == place], two_handed=False)
        ranked = []
        for origin, rotation, tidy in mount_candidates(place):
            local = (bone, qrot(qconj(bone_rot), sub(origin, bone_pos)), qnorm(qmul(qconj(bone_rot), rotation)))
            trial = {i: local for i in LOADOUTS["_mount"]["items"]}
            depth, where = deepest_of(trial, coarse_worlds, coarse_bodies)
            ranked.append((cost_of(tidy, depth), tidy, local, origin))
            if os.environ.get("SLASH_MOUNT_DEBUG") == place:
                unreal.log_warning("SLASH mount {} at ({:.0f},{:.0f},{:.0f}) tidy={:.0f}: depth {:.1f} ({})".format(
                    place, origin[0], origin[1], origin[2], tidy, depth, where))
        ranked.sort(key=lambda c: c[0])
        best = None
        for _, tidy, local, origin in ranked[:40]:
            trial = {i: local for i in LOADOUTS["_mount"]["items"]}
            depth, where = deepest_of(trial, worlds, bodies)
            cost = cost_of(tidy, depth)
            if best is None or cost < best[0]:
                best = (cost, local, depth, origin, where)
        _, local, depth, origin, where = best
        solved[place] = local
        mounts[item] = local
        unreal.log_warning("SLASH sheathed {} on {}: at ({:.0f},{:.0f},{:.0f}), closest to the body over every frame of standing, walking and running {:.1f} cm ({})".format(
            item, bone, origin[0], origin[1], origin[2], -depth, where))
    del LOADOUTS["_mount"]

    # Everything together, with the plain locomotion arms
    worst = {}
    for world in worlds:
        for label, (depth, where) in measure(surface, world, sheathed["loadout"], False, mounts).items():
            if label not in worst or depth > worst[label][0]:
                worst[label] = (depth, where)
    bad = [(d, label, where) for label, (d, where) in worst.items() if d > 0.5]
    for depth, label, where in sorted(bad, reverse=True):
        unreal.log_warning("SLASH sheathed {}: PENETRATION {:.1f} cm  {} ({})".format(sheathed["loadout"], depth, label, where))
    if not bad:
        unreal.log_warning("SLASH sheathed {}: no surface passes through another (closest {:.1f} cm), arm swing damped by {:.0f}%".format(
            sheathed["loadout"], -max(d for d, _ in worst.values()), damping * 100.0))
    return mounts, len(bad)


def write_mounts(all_mounts):
    """Tools/mounts.json for the audit, and a C++ header with the same transforms for the game."""
    tools_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(tools_dir, "mounts.json"), "w") as f:
        json.dump({item: dict(bone=bone, position=list(pos), rotation=list(rot)) for item, (bone, pos, rot) in all_mounts.items()}, f, indent=2)
    lines = ["// Generated by Tools/create_attack_anims.py - do not edit by hand.",
             "// Where each weapon sits on the body when it is put away: its grip frame in the space of a bone.",
             "", "#pragma once", "", '#include "CoreMinimal.h"', "", "namespace OpenWorldMounts", "{"]
    for item, (bone, pos, rot) in sorted(all_mounts.items()):
        name = item[0].upper() + item[1:]
        lines.append('\tinline const FName {}Bone(TEXT("{}"));'.format(name, bone))
        lines.append("\tinline const FTransform {}(FQuat({:.6f}, {:.6f}, {:.6f}, {:.6f}), FVector({:.3f}, {:.3f}, {:.3f}));".format(
            name, rot[0], rot[1], rot[2], rot[3], pos[0], pos[1], pos[2]))
    lines += ["}", ""]
    header = os.path.join(tools_dir, "..", "Source", "OpenWorld", "OpenWorldGeneratedMounts.h")
    with open(header, "w", newline="\n") as f:
        f.write("\n".join(lines))
    unreal.log_warning("SLASH wrote mounts for {}".format(", ".join(sorted(all_mounts))))


def main():
    rig = Rig()
    surface = BodySurface(rig)
    locomotion = []
    for path, count in LOCOMOTION:
        anim = unreal.load_asset(path)
        for index in range(count):
            locomotion.append(rig.pose_at(anim, anim.get_play_length() * index / count))
    # The put-away weapons are placed against every frame of the locomotion, the same sampling the audit uses:
    # a hand or a heel passes a hilt or a blade tip only for a frame or two.
    every_frame = []
    for path, _ in LOCOMOTION:
        anim = unreal.load_asset(path)
        # the idle pose hardly moves: a few samples are enough there
        count = 6 if "Idle" in path else max(1, int(round(anim.get_play_length() * 30.0)))
        for index in range(count + 1):
            every_frame.append(rig.pose_at(anim, anim.get_play_length() * index / count))

    only = os.environ.get("SLASH_ONLY")
    mounts_only = os.environ.get("SLASH_MOUNTS_ONLY") == "1"
    failures = 0
    all_mounts = {}
    for key, setup in SETUPS.items():
        if only and key != only:
            continue
        mounts, bad = place_sheathed(rig, surface, setup, locomotion, every_frame)
        all_mounts.update(mounts)
        failures += bad
        if not mounts_only:
            failures += generate(rig, surface, setup, locomotion)
    if (not PREVIEW_ONLY or mounts_only) and not only:
        write_mounts(all_mounts)
    unreal.log_warning("SLASH total penetrations: {}".format(failures))


if True:  # run as a script by the Python commandlet
    main()
