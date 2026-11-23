"""
Measures interpenetration of the character's body, weapons and shield, the way they are combined in the game.
Project rule: nothing passes through anything (see CLAUDE.md). Depths are in cm; > TOLERANCE is a failure.

For every loadout it checks:
  - the weapons put away on the body (Tools/mounts.json) while standing, walking and running,
  - the combat stance (arms holding the weapons) layered over standing, walking and running,
  - the attack played by the whole body (standing),
  - the attack played by the upper body over walking and running.
"unarmed" checks the plain locomotion animations and is a sanity check of the collision model itself.

Run (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/audit_collisions.py -unattended -nosplash -NullRHI

Set AUDIT_IMAGE=1 to also write Saved/Collision/<mesh>_surface.png (the fitted body surface, front and side).
Not covered: blends between animations, foot IK, and anything that happens only at runtime.
"""
import json
import math
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owlib  # noqa: E402
from owlib import SHEATHED_ARM_DAMPING, BodySurface, Rig, damp_arms, measure  # noqa: E402

TOLERANCE = 0.5     # cm; surfaces overlapping less than this count as touching
SAMPLES_PER_SECOND = 30
LOCOMOTION_PHASES = 8   # locomotion poses each attack frame is combined with

IDLE = "/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle"
WALK = "/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd"
JOG = "/Game/Characters/Mannequins/Anims/Unarmed/Jog/MF_Unarmed_Jog_Fwd"

# loadout -> (stance animation, attack animation, both hands on one weapon)
LOADOUT_ANIMS = {
    "sword_shield": ("/Game/Weapons/Sword/Anims/AS_Stance_SwordShield", "/Game/Weapons/Sword/Anims/AS_SwordSlash", False),
    "greatsword": ("/Game/Weapons/Greatsword/Anims/AS_Stance_Greatsword", "/Game/Weapons/Greatsword/Anims/AS_GreatswordSlash", True),
}
# The same bone groups the game layers (OpenWorldAnimInstance)
STANCE_ROOTS = {"upperarm_l", "upperarm_r"}
UPPER_BODY_ROOT = {"spine_01"}


def times_of(anim, per_second=SAMPLES_PER_SECOND):
    length = anim.get_play_length()
    count = max(1, int(round(length * per_second)))
    return [min(length, i * length / count) for i in range(count + 1)]


def layered(base, top, bones):
    out = dict(base)
    for bone in bones:
        out[bone] = top[bone]
    return out


class Audit:
    def __init__(self):
        self.rig = Rig()
        self.surface = BodySurface(self.rig)
        self.failures = 0
        self.arms = [b for b in self.rig.bones if self.rig.ancestor_in(b, STANCE_ROOTS)]
        self.upper = [b for b in self.rig.bones if self.rig.ancestor_in(b, UPPER_BODY_ROOT)]

    def poses(self, path, per_second=SAMPLES_PER_SECOND):
        anim = unreal.load_asset(path)
        if not anim:
            raise RuntimeError("Missing animation " + path)
        return [(t, self.rig.pose_at(anim, t)) for t in times_of(anim, per_second)]

    def check(self, label, loadout, gripping, poses, mounts=None):
        """poses: iterable of (description, local pose). mounts: items carried on the body."""
        worst = {}
        for description, local in poses:
            world = self.rig.fk(local)
            for name, (depth, where) in measure(self.surface, world, loadout, gripping, mounts).items():
                if name not in worst or depth > worst[name][0]:
                    worst[name] = (depth, where, description)
        bad = sorted(((d, n, w, at) for n, (d, w, at) in worst.items() if d > TOLERANCE), reverse=True)
        self.failures += len(bad)
        closest = -max(d for d, _, _ in worst.values())
        unreal.log_warning("AUDIT [{}] {}: {}".format(
            "FAIL" if bad else "ok", label,
            "{} penetrations".format(len(bad)) if bad else ("clear, closest {:.1f} cm".format(closest) if closest >= 0
                                                             else "touching, deepest {:.1f} cm".format(-closest))))
        for depth, name, where, at in bad:
            unreal.log_warning("AUDIT        {:5.1f} cm  {}  ({}) at {}".format(depth, name, where, at))

    def run(self):
        rig = self.rig
        unreal.log_warning("AUDIT character {}: {} surface spheres on {} bones, tolerance {} cm".format(
            rig.mesh.get_name(), self.surface.count, len([b for b, s in self.surface.spheres.items() if s]), TOLERANCE))
        locomotion = {"standing": self.poses(IDLE), "walking": self.poses(WALK), "running": self.poses(JOG)}

        for name, poses in locomotion.items():
            self.check("unarmed, " + name, "unarmed", False, (("t={:.2f}s".format(t), local) for t, local in poses))

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mounts.json")) as f:
            mounts = {item: (m["bone"], tuple(m["position"]), tuple(m["rotation"])) for item, m in json.load(f).items()}

        for loadout, (stance_path, attack_path, gripping) in LOADOUT_ANIMS.items():
            stance = self.poses(stance_path)[0][1]
            attack = self.poses(attack_path)
            # Not in combat: weapons on the body, hands free (arms calmed where the loadout says so)
            sheathed = loadout + "_sheathed"
            damping = SHEATHED_ARM_DAMPING.get(sheathed, 0.0)
            for name, poses in locomotion.items():
                self.check("{}: put away while {}".format(loadout, name), sheathed, False,
                           (("t={:.2f}s".format(t), damp_arms(rig, local, damping)) for t, local in poses), mounts)
            for name, poses in locomotion.items():
                self.check("{}: carried while {}".format(loadout, name), loadout, gripping,
                           (("t={:.2f}s".format(t), layered(local, stance, self.arms)) for t, local in poses))
            self.check("{}: attack, standing".format(loadout), loadout, gripping,
                       (("t={:.2f}s".format(t), local) for t, local in attack))
            for name in ("walking", "running"):
                cycle = locomotion[name]
                phases = [cycle[int(i * (len(cycle) - 1) / LOCOMOTION_PHASES)] for i in range(LOCOMOTION_PHASES)]
                self.check("{}: attack while {}".format(loadout, name), loadout, gripping,
                           (("attack t={:.2f}s over {} t={:.2f}s".format(t, name, tl), layered(base, local, self.upper))
                            for t, local in attack for tl, base in phases))
        unreal.log_warning("AUDIT total penetrations over tolerance: {}".format(self.failures))


def draw_surface(rig, surface, path):
    """Front and side view of the fitted spheres in the idle pose, to check them against the mesh by eye."""
    canvas = owlib.Canvas(520, 420)
    for bone, centre, radius in surface.place(rig.idle_world):
        for cx, cy in ((130 - centre[0] * 2, 400 - centre[2] * 2), (390 + centre[1] * 2, 400 - centre[2] * 2)):
            for ang in range(0, 360, 10):
                canvas.dot(cx + radius * 2 * math.cos(math.radians(ang)), cy + radius * 2 * math.sin(math.radians(ang)), (60, 110, 200), 0)
    canvas.save(path)
    unreal.log_warning("AUDIT surface image written to " + path)


audit = Audit()
if os.environ.get("AUDIT_IMAGE") == "1":
    draw_surface(audit.rig, audit.surface, os.path.join(unreal.Paths.project_saved_dir(), "Collision", audit.rig.mesh.get_name() + "_surface.png"))
audit.run()
