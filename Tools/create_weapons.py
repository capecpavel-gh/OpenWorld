"""
Builds the weapon Static Mesh assets and their materials:
  /Game/Weapons/Sword/SM_Sword            one-handed sword
  /Game/Weapons/Greatsword/SM_Greatsword  two-handed sword
  /Game/Weapons/Shield/SM_Shield          round centre-grip shield

Run (Unreal Editor must be closed):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/create_weapons.py -unattended -nosplash -NullRHI

Mesh axes match the HandGrip_R / HandGrip_L sockets of the mannequin:
  Swords: +Z = blade direction, Y = blade width (edges), X = blade thickness.
          The origin is where the right hand holds the grip.
  Shield: +X = outward face (back of the left hand), +Z = up (thumb side), origin = centre of the handle.
"""
import unreal

MATERIAL_DIR = "/Game/Weapons/Materials"

# name -> (base colour, metallic, roughness)
MATERIALS = {
    "MI_Sword_Blade": (unreal.LinearColor(0.75, 0.77, 0.80, 1.0), 1.0, 0.22),
    "MI_Sword_Guard": (unreal.LinearColor(0.80, 0.55, 0.20, 1.0), 1.0, 0.35),
    "MI_Sword_Grip": (unreal.LinearColor(0.12, 0.06, 0.03, 1.0), 0.0, 0.75),
    "MI_Shield_Wood": (unreal.LinearColor(0.23, 0.11, 0.05, 1.0), 0.0, 0.80),
    "MI_Shield_Metal": (unreal.LinearColor(0.55, 0.56, 0.58, 1.0), 1.0, 0.38),
}

# Dimensions in centimetres. grip_below / grip_above: grip length below and above the right hand.
SWORDS = {
    "/Game/Weapons/Sword/SM_Sword": dict(
        grip_below=6.0, grip_above=6.0, grip_radius=1.5, guard_width=20.0, guard_thickness=2.4, guard_height=2.4,
        blade_length=80.0, blade_half_width=2.5, blade_thickness=0.8, pommel_radius=2.2, pommel_height=3.0),
    "/Game/Weapons/Greatsword/SM_Greatsword": dict(
        grip_below=20.0, grip_above=7.0, grip_radius=1.6, guard_width=28.0, guard_thickness=2.8, guard_height=2.8,
        blade_length=108.0, blade_half_width=3.2, blade_thickness=1.0, pommel_radius=2.8, pommel_height=4.0),
}
SWORD_SLOTS = ["MI_Sword_Blade", "MI_Sword_Guard", "MI_Sword_Grip"]
BLADE, GUARD, GRIP = 0, 1, 2

SHIELD_PATH = "/Game/Weapons/Shield/SM_Shield"
# plate_offset: the plate starts this far in front of the grip, so the forearm lies behind it without touching (arm-strap shield)
SHIELD = dict(radius=30.0, plate_thickness=2.0, plate_offset=8.0, rim_extra=1.6, rim_thickness=0.8,
              boss_radius=7.0, boss_depth=0.4, handle_length=22.0, handle_thickness=2.4)
SHIELD_SLOTS = ["MI_Shield_Wood", "MI_Shield_Metal"]
WOOD, METAL = 0, 1

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
prims = unreal.GeometryScript_Primitives
BASE = unreal.GeometryScriptPrimitiveOriginMode.BASE
CENTER = unreal.GeometryScriptPrimitiveOriginMode.CENTER


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


def create_materials():
    base = create_base_material()
    result = {}
    for name, (color, metallic, roughness) in MATERIALS.items():
        mi, _ = get_or_create(name, MATERIAL_DIR, unreal.MaterialInstanceConstant,
                              unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, base)
        mel.set_material_instance_vector_parameter_value(mi, "BaseColor", color)
        mel.set_material_instance_scalar_parameter_value(mi, "Metallic", metallic)
        mel.set_material_instance_scalar_parameter_value(mi, "Roughness", roughness)
        mel.update_material_instance(mi)
        eal.save_loaded_asset(mi)
        result[name] = mi
    return result


def options(material_id):
    opts = unreal.GeometryScriptPrimitiveOptions()
    opts.material_id = material_id
    opts.polygroup_mode = unreal.GeometryScriptPrimitivePolygroupMode.PER_FACE
    return opts


def transform(x=0.0, y=0.0, z=0.0, rotation=None, scale=(1.0, 1.0, 1.0)):
    return unreal.Transform(location=unreal.Vector(x, y, z), rotation=rotation or unreal.Rotator(0, 0, 0),
                            scale=unreal.Vector(*scale))


def build_sword(d):
    mesh = unreal.new_object(unreal.DynamicMesh)
    grip_length = d["grip_below"] + d["grip_above"]

    # Grip (octagonal, leather)
    prims.append_cylinder(mesh, options(GRIP), transform(z=-d["grip_below"]), radius=d["grip_radius"],
                          height=grip_length, radial_steps=8, height_steps=0, capped=True, origin=BASE)
    # Cross guard, wide along Y like the blade edges
    guard_base = d["grip_above"]
    prims.append_box(mesh, options(GUARD), transform(z=guard_base), dimension_x=d["guard_thickness"],
                     dimension_y=d["guard_width"], dimension_z=d["guard_height"],
                     steps_x=0, steps_y=0, steps_z=0, origin=BASE)
    # Pommel
    prims.append_cylinder(mesh, options(GUARD), transform(z=-d["grip_below"] - d["pommel_height"]),
                          radius=d["pommel_radius"], height=d["pommel_height"], radial_steps=8, height_steps=0,
                          capped=True, origin=BASE)
    # Blade: side profile drawn in the polygon's XY plane, then rotated so that
    # profile X -> world Y (width), profile Y -> world Z (length), extrusion -> world X (thickness)
    blade_base = guard_base + d["guard_height"]
    w = d["blade_half_width"]
    tip_start = d["blade_length"] * 0.86
    profile = [
        unreal.Vector2D(-w, 0.0),
        unreal.Vector2D(w, 0.0),
        unreal.Vector2D(w * 0.8, tip_start),
        unreal.Vector2D(0.0, d["blade_length"]),
        unreal.Vector2D(-w * 0.8, tip_start),
    ]
    blade_rotation = unreal.MathLibrary.make_rot_from_xy(unreal.Vector(0, 1, 0), unreal.Vector(0, 0, 1))
    prims.append_simple_extrude_polygon(mesh, options(BLADE),
                                        transform(x=-d["blade_thickness"] / 2.0, z=blade_base, rotation=blade_rotation),
                                        profile, height=d["blade_thickness"], height_steps=0, capped=True, origin=BASE)
    return mesh


def build_shield(d):
    mesh = unreal.new_object(unreal.DynamicMesh)
    facing_out = unreal.MathLibrary.make_rot_from_z(unreal.Vector(1, 0, 0))   # cylinder axis along +X

    # Metal backing disc; its edge shows as a rim around the wooden plate
    prims.append_cylinder(mesh, options(METAL), transform(x=d["plate_offset"] - d["rim_thickness"], rotation=facing_out),
                          radius=d["radius"] + d["rim_extra"], height=d["rim_thickness"] + 0.6,
                          radial_steps=40, height_steps=0, capped=True, origin=BASE)
    # Wooden plate
    prims.append_cylinder(mesh, options(WOOD), transform(x=d["plate_offset"], rotation=facing_out),
                          radius=d["radius"], height=d["plate_thickness"], radial_steps=40, height_steps=0,
                          capped=True, origin=BASE)
    # Boss in the middle of the face: a flattened dome that does not reach behind the plate
    prims.append_sphere_lat_long(mesh, options(METAL),
                                 transform(x=d["plate_offset"] + d["plate_thickness"], scale=(d["boss_depth"], 1.0, 1.0)),
                                 radius=d["boss_radius"], steps_phi=10, steps_theta=18, origin=CENTER)
    # Handle (vertical bar the hand closes around) and the two posts joining it to the plate
    t = d["handle_thickness"]
    prims.append_box(mesh, options(WOOD), transform(), dimension_x=t, dimension_y=t, dimension_z=d["handle_length"],
                     steps_x=0, steps_y=0, steps_z=0, origin=CENTER)
    for z in (d["handle_length"] / 2.0 - t / 2.0, -d["handle_length"] / 2.0 + t / 2.0):
        prims.append_box(mesh, options(METAL), transform(x=d["plate_offset"] / 2.0, z=z),
                         dimension_x=d["plate_offset"], dimension_y=t, dimension_z=t,
                         steps_x=0, steps_y=0, steps_z=0, origin=CENTER)
    return mesh


def save_static_mesh(mesh, asset_path, slot_materials, collision_method):
    if eal.does_asset_exist(asset_path):
        # Rewrite in place: the character references these meshes, so they can not be deleted and recreated
        static_mesh = unreal.load_asset(asset_path)
        copy_options = unreal.GeometryScriptCopyMeshToAssetOptions()
        copy_options.enable_recompute_normals = False
        copy_options.enable_recompute_tangents = True
        copy_options.replace_materials = False
        unreal.GeometryScript_AssetUtils.copy_mesh_to_static_mesh(mesh, static_mesh, copy_options, unreal.GeometryScriptMeshWriteLOD())
    else:
        create_options = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
        create_options.enable_recompute_normals = False
        create_options.enable_recompute_tangents = True
        create_options.enable_nanite = False
        create_options.enable_collision = False
        result = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(mesh, asset_path, create_options)
        static_mesh = result[0] if isinstance(result, (tuple, list)) else result
        if not static_mesh:
            raise RuntimeError("Static mesh was not created: {}".format(result))

    # One material slot per material ID used in the dynamic mesh
    slots = static_mesh.get_editor_property("static_materials")
    if len(slots) != len(slot_materials):
        raise RuntimeError("{}: expected {} material slots, got {}".format(asset_path, len(slot_materials), len(slots)))
    for index, material in enumerate(slot_materials):
        static_mesh.set_material(index, material)

    # Collision surface that matches what is drawn: one tight shape per part of the mesh (project rule, see CLAUDE.md)
    collision = unreal.GeometryScript_Collision
    collision_options = unreal.GeometryScriptCollisionFromMeshOptions()
    collision_options.method = collision_method
    collision_options.max_shape_count = 0
    collision_options.emit_transaction = False
    collision.set_static_mesh_collision_from_mesh(mesh, static_mesh, collision_options)
    shapes = collision.get_simple_collision_shape_count(collision.get_simple_collision_from_static_mesh(static_mesh))
    eal.save_loaded_asset(static_mesh)

    bounds = static_mesh.get_bounding_box()
    unreal.log_warning("WEAPON {} min=({:.1f},{:.1f},{:.1f}) max=({:.1f},{:.1f},{:.1f}) collision shapes={} materials={}".format(
        asset_path, bounds.min.x, bounds.min.y, bounds.min.z, bounds.max.x, bounds.max.y, bounds.max.z,
        shapes, [m.get_name() for m in slot_materials]))


def main():
    materials = create_materials()
    for path, dimensions in SWORDS.items():
        save_static_mesh(build_sword(dimensions), path, [materials[name] for name in SWORD_SLOTS],
                         unreal.GeometryScriptCollisionGenerationMethod.ORIENTED_BOXES)
    save_static_mesh(build_shield(SHIELD), SHIELD_PATH, [materials[name] for name in SHIELD_SLOTS],
                     unreal.GeometryScriptCollisionGenerationMethod.CONVEX_HULLS)


main()
