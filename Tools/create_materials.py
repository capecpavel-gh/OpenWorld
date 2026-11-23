"""
Builds the substances of the game: textures, materials and physical materials for steel and wood.
  /Game/Materials/Substances/T_<Substance>_BaseColor / _Normal / _Roughness   generated tileable textures
  /Game/Materials/Substances/M_Substance                                      textured base material
  /Game/Materials/Substances/MI_Steel, MI_SteelDark, MI_Wood                  what meshes use
  /Game/Materials/Substances/PM_Steel, PM_Wood                                physical materials (OpenWorldPhysicalMaterial)

A physical material carries Unreal's friction, restitution and density plus the game's hardness and
toughness, which decide what a weapon contact does (see OpenWorldCharacter::ResolveContact).

Run before create_weapons.py (Unreal Editor must be closed; the C++ module must be built):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject
      -run=pythonscript -script=C:/Dev/OpenWorld/Tools/create_materials.py -unattended -nosplash -NullRHI
"""
import math
import os
import random
import struct
import zlib

import unreal

OUT_DIR = "/Game/Materials/Substances"
SIZE = 512
SOURCE_DIR = os.path.join(unreal.Paths.project_saved_dir(), "GeneratedTextures")

# name -> physical properties. Density in g/cm3; hardness on a Mohs-like scale; toughness relative to 1.
SUBSTANCES = {
    "Steel": dict(friction=0.6, restitution=0.25, density=7.85, hardness=7.5, toughness=4.0),
    "Wood": dict(friction=0.5, restitution=0.15, density=0.70, hardness=2.5, toughness=1.0),
}
# material instance -> (substance, tint, metallic, roughness scale, texture size in cm)
INSTANCES = {
    "MI_Steel": ("Steel", (1.00, 1.00, 1.00), 1.0, 1.0, 24.0),
    "MI_SteelDark": ("Steel", (0.42, 0.40, 0.38), 1.0, 1.35, 16.0),
    "MI_Wood": ("Wood", (1.00, 1.00, 1.00), 0.0, 1.0, 42.0),
}

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary


# ---------------------------------------------------------------- texture generation (tileable)

class Noise:
    """Tileable value noise: a random lattice of period x period cells, smoothly interpolated."""

    def __init__(self, seed, period_x, period_y):
        rng = random.Random(seed)
        self.px, self.py = period_x, period_y
        self.grid = [[rng.random() for _ in range(period_x)] for _ in range(period_y)]

    def at(self, u, v):
        """u, v in 0..1 over the whole texture."""
        x, y = u * self.px, v * self.py
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - x0, y - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        g = self.grid
        a, b = g[y0 % self.py][x0 % self.px], g[y0 % self.py][(x0 + 1) % self.px]
        c, d = g[(y0 + 1) % self.py][x0 % self.px], g[(y0 + 1) % self.py][(x0 + 1) % self.px]
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def steel_fields():
    """Brushed steel: long fine streaks along v, faint cloudy patches. Returns (colour, height, roughness) functions."""
    streaks = Noise(11, 256, 6)
    fine = Noise(12, 512, 24)
    clouds = Noise(13, 6, 6)

    def sample(u, v):
        s = 0.65 * streaks.at(u, v) + 0.35 * fine.at(u, v)
        c = clouds.at(u, v)
        shade = 0.56 + 0.10 * s + 0.07 * (c - 0.5)
        colour = (shade * 0.97, shade * 0.99, shade * 1.03)      # a cool grey
        return colour, 0.5 + 0.5 * (s - 0.5), 0.26 + 0.20 * s + 0.08 * c
    return sample


def wood_fields():
    """Oak-like planks: grain running along v, wavy growth lines, fine fibres. Returns the same triple."""
    warp = Noise(21, 5, 3)
    fibres = Noise(22, 256, 10)
    tone = Noise(23, 4, 2)
    dark, light = (0.19, 0.10, 0.045), (0.47, 0.29, 0.14)

    def sample(u, v):
        lines = 0.5 + 0.5 * math.sin(2.0 * math.pi * (9.0 * u + 1.6 * warp.at(u, v)))
        lines = lines ** 1.6
        f = fibres.at(u, v)
        t = max(0.0, min(1.0, 0.62 * lines + 0.28 * f + 0.25 * (tone.at(u, v) - 0.5)))
        colour = tuple(dark[i] + (light[i] - dark[i]) * t for i in range(3))
        return colour, 0.55 * lines + 0.45 * f, 0.62 + 0.22 * (1.0 - lines) + 0.08 * f
    return sample


def write_png(path, pixels, size):
    raw = b"".join(b"\x00" + bytes(pixels[y * size * 3:(y + 1) * size * 3]) for y in range(size))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def to_srgb(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def generate_textures(name, sample, bump):
    """Writes <name>_BaseColor/_Normal/_Roughness PNGs and returns their paths."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    colour = bytearray(SIZE * SIZE * 3)
    rough = bytearray(SIZE * SIZE * 3)
    normal = bytearray(SIZE * SIZE * 3)
    heights = [0.0] * (SIZE * SIZE)
    for y in range(SIZE):
        for x in range(SIZE):
            c, h, r = sample(x / SIZE, y / SIZE)
            i = (y * SIZE + x) * 3
            colour[i:i + 3] = bytes(int(255 * to_srgb(k) + 0.5) for k in c)
            value = int(255 * max(0.0, min(1.0, r)) + 0.5)
            rough[i:i + 3] = bytes((value, value, value))
            heights[y * SIZE + x] = h
    # Normal map from the height field (wrapping, so it tiles like the rest)
    for y in range(SIZE):
        for x in range(SIZE):
            dx = (heights[y * SIZE + (x + 1) % SIZE] - heights[y * SIZE + (x - 1) % SIZE]) * bump
            dy = (heights[((y + 1) % SIZE) * SIZE + x] - heights[((y - 1) % SIZE) * SIZE + x]) * bump
            length = math.sqrt(dx * dx + dy * dy + 1.0)
            i = (y * SIZE + x) * 3
            normal[i:i + 3] = bytes((int(255 * (0.5 - 0.5 * dx / length) + 0.5), int(255 * (0.5 - 0.5 * dy / length) + 0.5),
                                     int(255 * (0.5 + 0.5 / length) + 0.5)))
    paths = {}
    for kind, pixels in (("BaseColor", colour), ("Normal", normal), ("Roughness", rough)):
        paths[kind] = os.path.join(SOURCE_DIR, "T_{}_{}.png".format(name, kind))
        write_png(paths[kind], pixels, SIZE)
    return paths


def import_texture(path, kind):
    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = OUT_DIR
    task.automated = True
    task.replace_existing = True
    task.save = True
    asset_tools.import_asset_tasks([task])
    texture = unreal.load_asset(OUT_DIR + "/" + os.path.splitext(os.path.basename(path))[0])
    if kind == "Normal":
        texture.set_editor_property("srgb", False)
        texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    elif kind == "Roughness":
        texture.set_editor_property("srgb", False)
        texture.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
    eal.save_loaded_asset(texture)
    return texture


# ---------------------------------------------------------------- materials

def build_base_material(defaults):
    """M_Substance: base colour, normal and roughness textures laid out in the mesh's own space,
    so their scale is in centimetres and does not depend on the mesh's UVs."""
    path = OUT_DIR + "/M_Substance"
    if eal.does_asset_exist(path):
        return unreal.load_asset(path)
    material = asset_tools.create_asset("M_Substance", OUT_DIR, unreal.Material, unreal.MaterialFactoryNew())

    def node(cls, x, y):
        return mel.create_material_expression(material, cls, x, y)

    # UVs = (local Y, local Z) / TextureSize. Falls back to the mesh UVs if the node is unavailable.
    size = node(unreal.MaterialExpressionScalarParameter, -1100, 150)
    size.set_editor_property("parameter_name", "TextureSize")
    size.set_editor_property("default_value", 30.0)
    if hasattr(unreal, "MaterialExpressionLocalPosition"):
        position = node(unreal.MaterialExpressionLocalPosition, -1300, 0)
        mask = node(unreal.MaterialExpressionComponentMask, -1100, 0)
        mask.set_editor_property("r", False)
        mask.set_editor_property("g", True)
        mask.set_editor_property("b", True)
        mask.set_editor_property("a", False)
        mel.connect_material_expressions(position, "", mask, "")
        uvs = node(unreal.MaterialExpressionDivide, -900, 50)
        mel.connect_material_expressions(mask, "", uvs, "A")
        mel.connect_material_expressions(size, "", uvs, "B")
        mapping = "local position"
    else:
        uvs = node(unreal.MaterialExpressionTextureCoordinate, -900, 50)
        mapping = "mesh UVs"

    samples = {}
    for index, (kind, sampler) in enumerate((("BaseColor", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR),
                                             ("Normal", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL),
                                             ("Roughness", unreal.MaterialSamplerType.SAMPLERTYPE_MASKS))):
        sample = node(unreal.MaterialExpressionTextureSampleParameter2D, -650, -250 + index * 260)
        sample.set_editor_property("parameter_name", kind + "Texture")
        sample.set_editor_property("texture", defaults[kind])
        sample.set_editor_property("sampler_type", sampler)
        mel.connect_material_expressions(uvs, "", sample, "UVs")
        samples[kind] = sample

    tint = node(unreal.MaterialExpressionVectorParameter, -650, -450)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
    colour = node(unreal.MaterialExpressionMultiply, -300, -300)
    mel.connect_material_expressions(samples["BaseColor"], "RGB", colour, "A")
    mel.connect_material_expressions(tint, "", colour, "B")

    rough_scale = node(unreal.MaterialExpressionScalarParameter, -650, 560)
    rough_scale.set_editor_property("parameter_name", "RoughnessScale")
    rough_scale.set_editor_property("default_value", 1.0)
    rough = node(unreal.MaterialExpressionMultiply, -300, 300)
    mel.connect_material_expressions(samples["Roughness"], "R", rough, "A")
    mel.connect_material_expressions(rough_scale, "", rough, "B")

    metallic = node(unreal.MaterialExpressionScalarParameter, -300, 80)
    metallic.set_editor_property("parameter_name", "Metallic")
    metallic.set_editor_property("default_value", 0.0)

    mel.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(samples["Normal"], "RGB", unreal.MaterialProperty.MP_NORMAL)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    mel.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)
    mel.recompile_material(material)
    eal.save_loaded_asset(material)
    unreal.log_warning("MATERIAL M_Substance created, textures mapped by {}".format(mapping))
    return material


def build_physical_material(name, props):
    path = OUT_DIR + "/PM_" + name
    if eal.does_asset_exist(path):
        physical = unreal.load_asset(path)
    else:
        factory = unreal.PhysicalMaterialFactoryNew()
        factory.set_editor_property("physical_material_class", unreal.OpenWorldPhysicalMaterial)
        physical = asset_tools.create_asset("PM_" + name, OUT_DIR, unreal.OpenWorldPhysicalMaterial, factory)
    physical.set_editor_property("display_name", unreal.Text(name))
    for key in ("friction", "restitution", "density", "hardness", "toughness"):
        physical.set_editor_property(key, props[key])
    eal.save_loaded_asset(physical)
    unreal.log_warning("MATERIAL PM_{}: class {}, density {} g/cm3, hardness {}, toughness {}".format(
        name, physical.get_class().get_name(), props["density"], props["hardness"], props["toughness"]))
    return physical


def build_instance(name, base, textures, physical, tint, metallic, roughness_scale, texture_size):
    path = OUT_DIR + "/" + name
    if eal.does_asset_exist(path):
        instance = unreal.load_asset(path)
    else:
        instance = asset_tools.create_asset(name, OUT_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel.set_material_instance_parent(instance, base)
    for kind, texture in textures.items():
        mel.set_material_instance_texture_parameter_value(instance, kind + "Texture", texture)
    mel.set_material_instance_vector_parameter_value(instance, "Tint", unreal.LinearColor(tint[0], tint[1], tint[2], 1.0))
    mel.set_material_instance_scalar_parameter_value(instance, "Metallic", metallic)
    mel.set_material_instance_scalar_parameter_value(instance, "RoughnessScale", roughness_scale)
    mel.set_material_instance_scalar_parameter_value(instance, "TextureSize", texture_size)
    # Traces against a mesh that uses this material report this substance
    instance.set_editor_property("phys_material", physical)
    mel.update_material_instance(instance)
    eal.save_loaded_asset(instance)
    unreal.log_warning("MATERIAL {}: substance {}, texture repeats every {} cm".format(name, physical.get_name(), texture_size))


def main():
    fields = {"Steel": (steel_fields(), 2.0), "Wood": (wood_fields(), 5.0)}
    textures = {}
    for name, (sample, bump) in fields.items():
        paths = generate_textures(name, sample, bump)
        textures[name] = {kind: import_texture(path, kind) for kind, path in paths.items()}
        unreal.log_warning("MATERIAL textures for {}: {}".format(name, ", ".join(t.get_name() for t in textures[name].values())))

    base = build_base_material(textures["Steel"])
    physical = {name: build_physical_material(name, props) for name, props in SUBSTANCES.items()}
    for name, (substance, tint, metallic, roughness_scale, texture_size) in INSTANCES.items():
        build_instance(name, base, textures[substance], physical[substance], tint, metallic, roughness_scale, texture_size)


main()
