"""
Makes the player's Anim Blueprint (ABP_Unarmed) a child of the C++ class OpenWorldAnimInstance.
That class plays the attack animations on top of the Blueprint's locomotion (upper body only while running).

Run once after building the C++ code (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/setup_anim_blueprint.py -unattended -nosplash -NullRHI
"""
import unreal

ANIM_BLUEPRINT = "/Game/Characters/Mannequins/Anims/Unarmed/ABP_Unarmed"
PARENT_CLASS = "/Script/OpenWorld.OpenWorldAnimInstance"

lib = unreal.BlueprintEditorLibrary
blueprint = unreal.load_asset(ANIM_BLUEPRINT)
parent = unreal.load_class(None, PARENT_CLASS)
if not blueprint or not parent:
    raise RuntimeError("Missing {} or {}".format(ANIM_BLUEPRINT, PARENT_CLASS))

current = lib.get_blueprint_parent_class(blueprint) if hasattr(lib, "get_blueprint_parent_class") else None
unreal.log_warning("ANIMBP parent before: {}".format(current.get_name() if current else "?"))
if current != parent:
    lib.reparent_blueprint(blueprint, parent)
lib.compile_blueprint(blueprint)
unreal.EditorAssetLibrary.save_loaded_asset(blueprint)

generated = lib.generated_class(blueprint)
unreal.log_warning("ANIMBP parent after: {} (generated class {})".format(
    lib.get_blueprint_parent_class(blueprint).get_name(), generated.get_name() if generated else None))
