"""
Shared code for the OpenWorld content scripts: vector/quaternion math, the character rig (forward
kinematics, two-bone IK) and the collision surfaces used to keep everything from interpenetrating.

Character space: +Y forward, +Z up, -X is the character's right side.
"""
import json
import math
import os

import unreal

PLAYER_MESH = "/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple"
IDLE_ANIM = "/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle"

RIGHT = (-1.0, 0.0, 0.0)
FWD = (0.0, 1.0, 0.0)
UP = (0.0, 0.0, 1.0)
DOWN = (0.0, 0.0, -1.0)

# HandGrip_R / HandGrip_L sockets relative to hand_r / hand_l (from the mannequin skeleton).
# In socket space: +Z = thumb side (blade direction), +Y = fingers, +X = character's left in a hanging hand.
GRIP_OFFSET = {"r": (-7.012134, 2.048732, 0.0), "l": (7.520928, -2.529256, 0.0)}
SOCKET_ROT = {"r": (0.0, 0.0, 0.70710678, 0.70710678), "l": (-0.70710678, -0.70710678, 0.0, 0.0)}
FINGER_AXIS = {"r": (-1.0, 0.0, 0.0), "l": (1.0, 0.0, 0.0)}   # direction of the fingers in hand space

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



# ---------------------------------------------------------------- skeleton / poses

def to_vec(v): return (v.x, v.y, v.z)
def to_quat(q): return qnorm((q.x, q.y, q.z, q.w))


class Rig:
    """Bone hierarchy and idle pose of a character, with the proportions of its own mesh."""

    def __init__(self, mesh_path=PLAYER_MESH, idle_path=IDLE_ANIM):
        self.mesh = unreal.load_asset(mesh_path)
        self.idle_anim = unreal.load_asset(idle_path)
        self.options = unreal.AnimPoseEvaluationOptions()
        # Evaluate animations on this mesh: its limb lengths differ from the skeleton's default mannequin
        self.options.set_editor_property("optional_skeletal_mesh", self.mesh)
        self.options.set_editor_property("should_retarget", True)

        ext = unreal.AnimPoseExtensions
        pose = ext.get_anim_pose_at_frame(self.idle_anim, 0, self.options)
        self.bones = [str(n) for n in ext.get_bone_names(pose)]
        self.parent = {}
        self.scale = {}
        for bone in self.bones:
            path = [str(n) for n in unreal.AnimationLibrary.find_bone_path_to_root(self.idle_anim, bone)]
            self.parent[bone] = path[1] if len(path) > 1 else None
        order = {bone: i for i, bone in enumerate(self.bones)}
        for bone in self.bones:
            parent = self.parent[bone]
            if parent is not None and order[parent] > order[bone]:
                raise RuntimeError("Bone order is not parent-first: " + bone)
        self.base = self._read(pose, with_scale=True)
        self.idle_world = self.fk(dict(self.base))

        # Unreal retargets the pelvis translation of an animation by the ratio of this mesh's size to the
        # skeleton's default mannequin ("AnimationScaled"). Poses here are already in this mesh's size, so
        # translations written into an animation asset must be divided by that ratio first.
        plain = ext.get_bone_pose(ext.get_anim_pose_at_frame(self.idle_anim, 0, unreal.AnimPoseEvaluationOptions()),
                                  "pelvis", unreal.AnimPoseSpaces.LOCAL).translation
        self.write_scale = {"pelvis": length(to_vec(plain)) / max(length(self.base["pelvis"][0]), 1e-6)}

    def _read(self, pose, with_scale=False):
        ext = unreal.AnimPoseExtensions
        local = {}
        for bone in self.bones:
            t = ext.get_bone_pose(pose, bone, unreal.AnimPoseSpaces.LOCAL)
            local[bone] = (to_vec(t.translation), to_quat(t.rotation))
            if with_scale:
                self.scale[bone] = to_vec(t.scale3d)
        return local

    def pose_at(self, anim, time):
        """Local pose of an animation asset at a time [s]."""
        return self._read(unreal.AnimPoseExtensions.get_anim_pose_at_time(anim, time, self.options))

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

    def ancestor_in(self, bone, names):
        """The bone itself or its nearest ancestor that is in `names` (None if there is none)."""
        while bone is not None and bone not in names:
            bone = self.parent.get(bone)
        return bone


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




# ---------------------------------------------------------------- collision surfaces
#
# Rule of the project: nothing passes through anything. The character's surface is modelled by spheres
# fitted to the real vertices of its mesh (per bone, so they follow any pose); weapons and shields by
# the simple shapes they are built from. "Penetration" below is how deep two surfaces overlap, in cm.

# Bones that own a part of the body surface; every other bone's vertices go to its nearest ancestor here.
MAJOR_BONES = [
    "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "head",
    "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l", "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
    "thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r",
]
FINGER_PREFIXES = ("thumb_", "index_", "middle_", "ring_", "pinky_")
TORSO = ["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "head"]
LEGS = ["thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r"]
SLICE_WIDTH = 3.0


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def principal_axis(points, mean):
    """Direction of largest spread of a point cloud (power iteration on the covariance matrix)."""
    c = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = sub(p, mean)
        for i in range(3):
            for j in range(3):
                c[i][j] += d[i] * d[j]
    axis = (1.0, 0.7, 0.4)
    for _ in range(40):
        axis = norm(tuple(sum(c[i][j] * axis[j] for j in range(3)) for i in range(3)))
    return axis


def fit_spheres(points, slice_width=SLICE_WIDTH, min_points=6):
    """Spheres hugging a point cloud: slices along its main axis, each covered by one sphere,
    or by a row of spheres where the cross-section is wide and flat (chest, pelvis, foot)."""
    if len(points) < min_points:
        return []
    mean = mul(tuple(sum(p[i] for p in points) for i in range(3)), 1.0 / len(points))
    axis = principal_axis(points, mean)
    u = norm(cross(axis, (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)))
    v = cross(axis, u)
    coords = [(dot(d, axis), dot(d, u), dot(d, v)) for d in (sub(p, mean) for p in points)]
    t_min = min(c[0] for c in coords)
    t_max = max(c[0] for c in coords)
    count = max(1, int(round((t_max - t_min) / slice_width)))
    width = max((t_max - t_min) / count, 1e-3)

    spheres = []
    for index in range(count):
        low = t_min + index * width
        high = low + width + (1e-6 if index == count - 1 else 0.0)
        cut = [(a, b) for t, a, b in coords if low <= t < high]
        if len(cut) < min_points:
            continue
        ca = sum(a for a, _ in cut) / len(cut)
        cb = sum(b for _, b in cut) / len(cut)
        sxx = sum((a - ca) ** 2 for a, _ in cut)
        syy = sum((b - cb) ** 2 for _, b in cut)
        sxy = sum((a - ca) * (b - cb) for a, b in cut)
        theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
        e1 = (math.cos(theta), math.sin(theta))
        major = percentile([abs((a - ca) * e1[0] + (b - cb) * e1[1]) for a, b in cut], 0.9)
        minor = max(0.5, percentile([abs(-(a - ca) * e1[1] + (b - cb) * e1[0]) for a, b in cut], 0.9))
        if major <= 1.3 * minor:
            offsets, radius = [0.0], 0.5 * (major + minor)
        else:
            n = int(math.ceil(major / minor))
            span = major - minor
            offsets, radius = [-span + 2.0 * span * j / (n - 1) for j in range(n)], minor
        for offset in offsets:
            a, b = ca + e1[0] * offset, cb + e1[1] * offset
            centre = add(add(add(mean, mul(axis, 0.5 * (low + high))), mul(u, a)), mul(v, b))
            spheres.append((centre, radius))
    return spheres


class BodySurface:
    """Spheres covering the character's skin, stored per bone in that bone's space."""

    def __init__(self, rig):
        self.rig = rig
        cache = os.path.join(unreal.Paths.project_saved_dir(), "Collision", rig.mesh.get_name() + "_spheres.json")
        if os.path.exists(cache) and os.environ.get("OW_REFIT") != "1":
            with open(cache) as f:
                self.spheres = {bone: [(tuple(c), r) for c, r in items] for bone, items in json.load(f).items()}
        else:
            self.spheres = self._fit()
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w") as f:
                json.dump(self.spheres, f)
        self.count = sum(len(s) for s in self.spheres.values())

    def _fit(self):
        rig = self.rig
        mesh = unreal.new_object(unreal.DynamicMesh)
        unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(
            rig.mesh, mesh, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
        weights = unreal.GeometryScript_BoneWeights
        queries = unreal.GeometryScript_MeshQueries

        # Bones of the mesh in its reference pose (mesh space)
        bones, by_name = {}, {}
        for info in weights.get_all_bones_info(mesh)[1]:
            t = info.world_transform
            bones[info.index] = (str(info.name), to_vec(t.translation), to_quat(t.rotation))
            by_name[str(info.name)] = info.index

        clouds = {bone: [] for bone in MAJOR_BONES}
        profile = unreal.GeometryScriptBoneWeightProfile()
        for vertex in range(queries.get_vertex_count(mesh)):
            result = weights.get_largest_vertex_bone_weight(mesh, vertex, profile)
            if not result[2]:
                continue
            name = bones[result[1].bone_index][0]
            if name.startswith(FINGER_PREFIXES):
                continue    # fingers change shape with the grip; the palm stands in for the hand
            owner = rig.ancestor_in(name, clouds)
            if owner is None:
                continue
            _, pos, rot = bones[by_name[owner]]
            point = queries.get_vertex_position(mesh, vertex)
            if isinstance(point, tuple):
                point = next(item for item in point if hasattr(item, "x"))
            # store the vertex in its owner bone's space, so the surface follows the bone in any pose
            clouds[owner].append(qrot(qconj(rot), sub(to_vec(point), pos)))

        return {bone: fit_spheres(points) for bone, points in clouds.items()}

    def place(self, world, bones=None):
        """World-space spheres [(bone, centre, radius)] of the given bones (all if None) in a pose."""
        placed = []
        for bone in (bones if bones is not None else self.spheres):
            pos, rot = world[bone]
            for centre, radius in self.spheres.get(bone, ()):
                placed.append((bone, add(pos, qrot(rot, centre)), radius))
        return placed


# Equipment shapes in the grip socket's space (see create_weapons.py for the dimensions).
#   blade:  flat capsule along +Z from z0 to z1, `half_width` along Y, `half_thickness` along X
#   bar:    capsule along Y at height z (cross guard)
#   disc:   shield plate facing +X, centre `offset` cm out from the grip
EQUIPMENT = {
    "sword": dict(hand="r", parts=[
        dict(kind="blade", name="sword blade", z0=8.4, z1=88.4, half_width=2.5, half_thickness=0.4),
        dict(kind="bar", name="sword guard", z=7.2, half_length=10.0, radius=1.2),
    ]),
    "greatsword": dict(hand="r", parts=[
        dict(kind="blade", name="greatsword blade", z0=9.8, z1=117.8, half_width=3.2, half_thickness=0.5),
        dict(kind="bar", name="greatsword guard", z=8.4, half_length=14.0, radius=1.4),
        dict(kind="blade", name="greatsword pommel", z0=-24.0, z1=-20.0, half_width=2.0, half_thickness=2.0),
    ]),
    "shield": dict(hand="l", parts=[
        dict(kind="disc", name="shield", offset=8.6, radius=31.6, half_thickness=1.4),
    ]),
}
# The scabbard hangs at the hip with the sword in it: it uses the sword's mount and covers the blade
EQUIPMENT["scabbard"] = dict(hand="l", parts=[
    dict(kind="blade", name="scabbard", z0=7.0, z1=91.0, half_width=3.4, half_thickness=1.4),
])
LOADOUTS = {
    "sword_shield": dict(items=["sword", "shield"], two_handed=False),
    "greatsword": dict(items=["greatsword"], two_handed=True),
    "unarmed": dict(items=[], two_handed=False),
    # weapons put away: every item sits on a mount on the body (see `mounts` in equipment_shapes)
    "sword_shield_sheathed": dict(items=["sword", "scabbard", "shield"], two_handed=False),
    "greatsword_sheathed": dict(items=["greatsword"], two_handed=False),
}


# With a big shield on the back the arms can not swing as far behind the body as the plain running
# animation does. In that state the game pulls the arms this far (0..1) toward their idle pose.
SHEATHED_ARM_DAMPING = {"sword_shield_sheathed": 0.5, "greatsword_sheathed": 0.0}
ARM_ROOTS = {"upperarm_l", "upperarm_r"}


def damp_arms(rig, pose, amount):
    """The pose with both arms pulled `amount` (0..1) of the way toward the idle pose."""
    if amount <= 0.0:
        return pose
    out = dict(pose)
    for bone in rig.bones:
        if rig.ancestor_in(bone, ARM_ROOTS):
            out[bone] = (pose[bone][0], qnorm(qslerp(pose[bone][1], rig.base[bone][1], amount)))
    return out


def equipment_shapes(world, loadout, mounts=None):
    """World-space shapes of everything the character carries: (name, hand side, [segments], radius) for
    capsule-like parts and (name, hand side, centre, normal, radius, half_thickness) for discs.
    mounts: {item: (bone, position, rotation)} puts an item on the body instead of in its hand; position
    and rotation are the item's grip frame in that bone's space. The hand side of a mounted item is ""."""
    capsules, discs = [], []
    for item in LOADOUTS[loadout]["items"]:
        spec = EQUIPMENT[item]
        if mounts and item in mounts:
            bone, local_pos, local_rot = mounts[item]
            pos, rot = world[bone]
            side = ""
            socket = qnorm(qmul(rot, local_rot))
            origin = add(pos, qrot(rot, local_pos))
        else:
            side = spec["hand"]
            pos, rot = world["hand_" + side]
            socket = qmul(rot, SOCKET_ROT[side])
            origin = add(pos, qrot(rot, GRIP_OFFSET[side]))
        x, y, z = qrot(socket, (1.0, 0.0, 0.0)), qrot(socket, (0.0, 1.0, 0.0)), qrot(socket, (0.0, 0.0, 1.0))
        for part in spec["parts"]:
            if part["kind"] == "blade":
                edge = part["half_width"] - part["half_thickness"]
                segments = [(add(add(origin, mul(z, part["z0"])), mul(y, k * edge)),
                             add(add(origin, mul(z, part["z1"])), mul(y, k * edge))) for k in (-1.0, 0.0, 1.0)]
                capsules.append((part["name"], side, segments, part["half_thickness"]))
            elif part["kind"] == "bar":
                mid = add(origin, mul(z, part["z"]))
                capsules.append((part["name"], side, [(sub(mid, mul(y, part["half_length"])), add(mid, mul(y, part["half_length"])))], part["radius"]))
            else:
                discs.append((part["name"], side, add(origin, mul(x, part["offset"])), x, part["radius"], part["half_thickness"]))
    return capsules, discs


def point_segment_distance(p, a, b):
    ab = sub(b, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / max(dot(ab, ab), 1e-9)))
    return length(sub(p, add(a, mul(ab, t))))


def point_disc_distance(p, centre, normal, radius, half_thickness):
    d = sub(p, centre)
    along = dot(d, normal)
    radial = length(sub(d, mul(normal, along)))
    dz = abs(along) - half_thickness
    dr = radial - radius
    if dz <= 0.0 and dr <= 0.0:
        return max(dz, dr)      # inside the plate: negative depth
    return math.sqrt(max(dz, 0.0) ** 2 + max(dr, 0.0) ** 2)


def deepest(spheres_a, spheres_b):
    """Deepest overlap between two sphere sets: (depth, bone_a, bone_b). Negative = clearance."""
    best = (-1e9, "", "")
    for bone_a, ca, ra in spheres_a:
        for bone_b, cb, rb in spheres_b:
            dx, dy, dz = ca[0] - cb[0], ca[1] - cb[1], ca[2] - cb[2]
            depth = ra + rb - math.sqrt(dx * dx + dy * dy + dz * dz)
            if depth > best[0]:
                best = (depth, bone_a, bone_b)
    return best


def deepest_capsule(segments, radius, spheres):
    best = (-1e9, "")
    for bone, centre, r in spheres:
        depth = r + radius - min(point_segment_distance(centre, a, b) for a, b in segments)
        if depth > best[0]:
            best = (depth, bone)
    return best


def deepest_disc(centre, normal, radius, half_thickness, spheres):
    best = (-1e9, "")
    for bone, c, r in spheres:
        depth = r - point_disc_distance(c, centre, normal, radius, half_thickness)
        if depth > best[0]:
            best = (depth, bone)
    return best


def measure(surface, world, loadout="unarmed", gripping=False, mounts=None):
    """All surface-vs-surface checks for one pose. Returns {label: (depth cm, where)}; depth > 0 is a penetration.
    gripping=True: both hands hold the same weapon, so the hands (and the weapon near them) may touch.
    mounts: items carried on the body instead of in the hands (see equipment_shapes)."""
    def spheres(bones):
        return surface.place(world, bones)

    torso, legs = spheres(TORSO), spheres(LEGS)
    result = {}
    for side in "lr":
        forearm = spheres(["lowerarm_" + side, "hand_" + side])
        depth, a, b = deepest(forearm, torso)
        result["forearm_{} vs torso".format(side)] = (depth, a + "/" + b)
        depth, a, b = deepest(forearm, legs)
        result["forearm_{} vs legs".format(side)] = (depth, a + "/" + b)
        # The upper arm always touches the chest at the armpit; check it against what it must stay clear of
        depth, a, b = deepest(spheres(["upperarm_" + side]), spheres(["pelvis", "spine_01", "spine_02", "head"]) + legs)
        result["upperarm_{} vs hips/head/legs".format(side)] = (depth, a + "/" + b)

    left = spheres(["lowerarm_l"] + ([] if gripping else ["hand_l"]))
    right = spheres(["upperarm_r", "lowerarm_r"] + ([] if gripping else ["hand_r"]))
    depth, a, b = deepest(left, right)
    result["forearm_l vs arm_r"] = (depth, a + "/" + b)
    depth, a, b = deepest(spheres(["lowerarm_r"] + ([] if gripping else ["hand_r"])), spheres(["upperarm_l"]))
    result["forearm_r vs upperarm_l"] = (depth, a + "/" + b)

    capsules, discs = equipment_shapes(world, loadout, mounts)
    for name, side, segments, radius in capsules:
        holding = (["hand_" + side] if side else []) + (["hand_l", "hand_r"] if gripping else [])
        body = spheres([b for b in MAJOR_BONES if b not in holding])
        depth, where = deepest_capsule(segments, radius, body)
        result[name + " vs body"] = (depth, where)
    for name, side, centre, normal, radius, half_thickness in discs:
        body = spheres([b for b in MAJOR_BONES if b != "hand_" + side])
        depth, where = deepest_disc(centre, normal, radius, half_thickness, body)
        result[name + " vs body"] = (depth, where)
        for other, other_side, segments, other_radius in capsules:
            # weapon against the shield: sample points along the weapon
            worst = -1e9
            for a, b in segments:
                for k in range(11):
                    worst = max(worst, other_radius - point_disc_distance(lerp(a, b, k / 10.0), centre, normal, radius, half_thickness))
            result[other + " vs " + name] = (worst, "")
    # Weapons are not checked against each other except against shields: a sheathed sword is inside its scabbard
    return result


# ---------------------------------------------------------------- tiny PNG writer (previews)

import struct
import zlib


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


