# OpenWorld

Third-person open world game in Unreal Engine 5.8 (C++ project, module `OpenWorld`).
The player character is `BP_ThirdPersonCharacter` (C++ parent `AOpenWorldCharacter`, mesh `SKM_Quinn_Simple`).

## Rule: nothing passes through anything

Every character and every asset (weapon, shield, prop) has its own tuned collision surface that tightly
covers its visible shape. Meshes and animations must never interpenetrate:

1. **Surfaces.** A new asset is not done until it has a collision surface that matches what is drawn.
   Characters get theirs from their own mesh (see `Tools/owlib.py`), not from a guess.
2. **Authored content.** Hold poses and animations must keep every surface outside every other surface
   (weapon vs body, shield vs arm, arm vs torso, hand vs hand unless gripping). This is checked by
   `Tools/audit_collisions.py`, not by eye. An animation with a measured penetration is not finished.
3. **Contact at runtime.** When two things meet, motion stops at the surface. What happens next is decided
   by physics (push, knock-back, deformation, damage), never by letting one mesh slide through the other.

When reporting work, give the audit's measured numbers. If something could not be checked against
surfaces, say so plainly.

## Tools (run with the Unreal Editor closed)

All scripts run through the editor's Python commandlet:

    "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject -run=pythonscript -script=C:/Dev/OpenWorld/Tools/<script>.py -unattended -nosplash -NullRHI

- `create_weapons.py` builds the weapon and shield meshes with their collision.
- `create_attack_anims.py` generates the attack animations (`SLASH_PREVIEW=1` only previews).
- `audit_collisions.py` measures interpenetration of body, weapons and shield over the animations.
- `setup_anim_blueprint.py` reparents `ABP_Unarmed` to `OpenWorldAnimInstance` (needed once).

In-game check without a window: `UnrealEditor-Cmd.exe OpenWorld.uproject -game -OWSelfTest -NullRHI`
and read the `OWSELFTEST` lines in the log.

## Notes

- Binary assets go through Git LFS. Generated folders are ignored (`.gitignore`).
- Animation lengths must be a multiple of 1/30 s (Unreal resamples to 30 fps when compressing).
