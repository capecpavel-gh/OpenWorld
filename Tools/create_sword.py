"""
Builds a simple one-handed sword as a Static Mesh asset, plus its materials.

Run from the repo root (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" OpenWorld.uproject
      -run=pythonscript -script=Tools/create_sword.py -unattended -nosplash -NullRHI

Mesh axes (attached to the HandGrip_R socket of the mannequin):
  +Z = blade direction, Y = blade width (edges), X = blade thickness.
  The middle of the grip is at the origin, where the palm holds it.
"""
import unreal

SWORD_DIR = "/Game/Weapons/Sword"
MATERIAL_DIR = "/Game/Weapons/Materials"
BASE_MATERIAL = MATERIAL_DIR + "/M_WeaponPart"

# Dimensions in centimetres
GRIP_LENGTH = 12.0
GRIP_RADIUS = 1.5
GUARD_WIDTH = 20.0
GUARD_THICKNESS = 2.4
GUARD_HEIGHT = 2.4
BLADE_LENGTH = 80.0
BLADE_HALF_WIDTH = 2.5
BLADE_THICKNESS = 0.8
POMMEL_RADIUS = 2.2
POMMEL_HEIGHT = 3.0

# material slot index -> (slot name, base colour, metallic, roughness)
PARTS = [
    ("Blade", unreal.LinearColor(0.75, 0.77, 0.80, 1.0), 1.0, 0.22),
    ("Guard", unreal.LinearColor(0.80, 0.55, 0.20, 1.0), 1.0, 0.35),
    ("Grip", unreal.LinearColor(0.12, 0.06, 0.03, 1.0), 0.0, 0.75),
]
BLADE, GUARD, GRIP = 0, 1, 2

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary


def get_or_create(name, folder, asset_class, factory):
    path = folder + "/" + name
    if eal.does_asset_exist(path):
        return eal.load_asset(path), False
    return asset_tools.create_asset(name, folder, asset_class, factory), True


def create_base_material():
    material, created = get_or_create("M_WeaponPart", MATERIAL_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if created:
        color = mel.create_material_expression(material, unreal.MaterialExpressionVectorParameter, -400, -200)
        color.set_editor_property("parameter_name", "BaseColor")
        color.set_editor_property("default_value", unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
        metallic = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -400, 0)
        metallic.set_editor_property("parameter_name", "Metallic")
        metallic.set_editor_property("default_value", 0.0)
        roughness = mel.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -400, 150)
        roughness.set_editor_property("parameter_name", "Roughness")
        roughness.set_editor_property("default_value", 0.5)
        mel.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
        mel.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)
        mel.connect_material_property(roughness, "", unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(material)
        eal.save_loaded_asset(material)
    return material


def create_part_material(base, name, color, metallic, roughness):
    mi, _ = get_or_create("MI_Sword_" + name, MATERIAL_DIR, unreal.MaterialInstanceConstant,
                          unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(mi, base)
    mel.set_material_instance_vector_parameter_value(mi, "BaseColor", color)
    mel.set_material_instance_scalar_parameter_value(mi, "Metallic", metallic)
    mel.set_material_instance_scalar_parameter_value(mi, "Roughness", roughness)
    mel.update_material_instance(mi)
    eal.save_loaded_asset(mi)
    return mi


def options(material_id):
    opts = unreal.GeometryScriptPrimitiveOptions()
    opts.material_id = material_id
    opts.polygroup_mode = unreal.GeometryScriptPrimitivePolygroupMode.PER_FACE
    return opts


def at(z, rotation=unreal.Rotator(0, 0, 0)):
    return unreal.Transform(location=unreal.Vector(0, 0, z), rotation=rotation, scale=unreal.Vector(1, 1, 1))


def build_mesh():
    prims = unreal.GeometryScript_Primitives
    mesh = unreal.new_object(unreal.DynamicMesh)
    half_grip = GRIP_LENGTH / 2.0

    # Grip (octagonal, leather)
    prims.append_cylinder(mesh, options(GRIP), at(-half_grip), radius=GRIP_RADIUS, height=GRIP_LENGTH,
                          radial_steps=8, height_steps=0, capped=True,
                          origin=unreal.GeometryScriptPrimitiveOriginMode.BASE)

    # Cross guard, wide along Y like the blade edges
    guard_base = half_grip
    prims.append_box(mesh, options(GUARD), at(guard_base), dimension_x=GUARD_THICKNESS, dimension_y=GUARD_WIDTH,
                     dimension_z=GUARD_HEIGHT, steps_x=0, steps_y=0, steps_z=0,
                     origin=unreal.GeometryScriptPrimitiveOriginMode.BASE)

    # Pommel
    prims.append_cylinder(mesh, options(GUARD), at(-half_grip - POMMEL_HEIGHT), radius=POMMEL_RADIUS,
                          height=POMMEL_HEIGHT, radial_steps=8, height_steps=0, capped=True,
                          origin=unreal.GeometryScriptPrimitiveOriginMode.BASE)

    # Blade: side profile drawn in the polygon's XY plane, then rotated so that
    # profile X -> world Y (width), profile Y -> world Z (length), extrusion -> world X (thickness)
    blade_base = guard_base + GUARD_HEIGHT
    w = BLADE_HALF_WIDTH
    tip_start = BLADE_LENGTH * 0.86
    profile = [
        unreal.Vector2D(-w, 0.0),
        unreal.Vector2D(w, 0.0),
        unreal.Vector2D(w * 0.8, tip_start),
        unreal.Vector2D(0.0, BLADE_LENGTH),
        unreal.Vector2D(-w * 0.8, tip_start),
    ]
    blade_rotation = unreal.MathLibrary.make_rot_from_xy(unreal.Vector(0, 1, 0), unreal.Vector(0, 0, 1))
    blade_transform = unreal.Transform(location=unreal.Vector(-BLADE_THICKNESS / 2.0, 0, blade_base),
                                       rotation=blade_rotation, scale=unreal.Vector(1, 1, 1))
    prims.append_simple_extrude_polygon(mesh, options(BLADE), blade_transform, profile,
                                         height=BLADE_THICKNESS, height_steps=0, capped=True,
                                         origin=unreal.GeometryScriptPrimitiveOriginMode.BASE)
    return mesh


def main():
    base = create_base_material()
    materials = [create_part_material(base, name, color, metallic, rough) for name, color, metallic, rough in PARTS]

    mesh = build_mesh()
    asset_path = SWORD_DIR + "/SM_Sword"
    if eal.does_asset_exist(asset_path):
        eal.delete_asset(asset_path)

    create_options = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
    create_options.enable_recompute_normals = False
    create_options.enable_recompute_tangents = True
    create_options.enable_nanite = False
    create_options.enable_collision = False
    result = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(
        mesh, asset_path, create_options)
    static_mesh = result[0] if isinstance(result, (tuple, list)) else result
    if not static_mesh:
        raise RuntimeError("Static mesh was not created: {}".format(result))

    # One material slot per material ID used in the dynamic mesh (Blade, Guard, Grip)
    slots = static_mesh.get_editor_property("static_materials")
    if len(slots) == len(materials):
        for index, (mi, (name, _, _, _)) in enumerate(zip(materials, PARTS)):
            static_mesh.set_material(index, mi)
    else:
        static_mesh.set_editor_property("static_materials", [
            unreal.StaticMaterial(material_interface=mi, material_slot_name=name)
            for mi, (name, _, _, _) in zip(materials, PARTS)
        ])
    eal.save_loaded_asset(static_mesh)

    bounds = static_mesh.get_bounding_box()
    unreal.log_warning("SWORD_CREATED {} slots_before={} sections={} materials={} bounds min={} max={}".format(
        asset_path, len(slots), static_mesh.get_num_sections(0),
        [m.material_interface.get_name() if m.material_interface else None
         for m in static_mesh.get_editor_property("static_materials")],
        bounds.min, bounds.max))


main()
