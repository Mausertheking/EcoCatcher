"""
EcoCatcher: parametric 3D model of the low-cost, zero-grid windcatcher.

Builds the tower, the single room it cools, and all six upgrades from the
study (evaporative pad, solar chimney, solar fans, smart louvers, insect &
dust mesh, thermal-mass lining) as separate, toggleable collections.

Dimensions follow Table 1 of the study: 0.6 x 0.6 m shafts, a 3 m tower
above a 3 m room (stack height H = 6 m), a 20 m2 room, 3 x 140 mm solar fans
and a 10 W panel. Units are metres, Z is up, the wind blows from -X (west)
to +X (east) and the sun is to the south (-Y).

Run it either way:

  * Inside Blender: open the Scripting workspace, load this file, press
    Run Script. Only the "EcoCatcher" collection is (re)built; the rest of
    your scene is left alone.

  * Headless:
      blender -b -P ecocatcher_model.py -- --blend EcoCatcher.blend \
              --glb EcoCatcher.glb --render renders/ --samples 96
    or, with the bpy module from PyPI (pip install bpy):
      python ecocatcher_model.py --blend EcoCatcher.blend ...
"""

import argparse
import math
import os
import sys

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

ROOT = "EcoCatcher"

# --------------------------------------------------------------------------
# Design parameters (metres)
# --------------------------------------------------------------------------
ROOM_X, ROOM_Y, ROOM_H = 5.0, 4.0, 3.0      # 20 m2 interior, 3 m ceiling
WALL = 0.30                                 # compressed-earth / rammed-earth wall
LINING = 0.05                               # clay thermal-mass lining
ROOF_T = 0.25
ROOF_TOP = ROOM_H + ROOF_T                  # 3.25
PARAPET_H = 0.35

SHAFT = 0.60                                # 0.6 x 0.6 m shaft -> A = 0.36 m2
T_WALL = 0.15                               # tower wall thickness
DIVIDER = 0.06
TOWER_TOP = ROOM_H + 3.0 + 0.2              # 3 m above the roof slab -> 6.2
OPEN_Z0, OPEN_Z1 = 4.90, 5.90               # wind openings
SUPPLY_H = 0.45                             # low supply opening into the room

# Tower plan: intake shaft (windward, west) | divider | exhaust shaft (east)
IN_X0, IN_X1 = 0.0, SHAFT
EX_X0, EX_X1 = SHAFT + DIVIDER, 2 * SHAFT + DIVIDER
SH_Y0 = ROOM_Y / 2 - SHAFT / 2              # 1.70
SH_Y1 = ROOM_Y / 2 + SHAFT / 2              # 2.30
TW_X0, TW_X1 = IN_X0 - T_WALL, EX_X1 + T_WALL
TW_Y0, TW_Y1 = SH_Y0 - T_WALL, SH_Y1 + T_WALL


# --------------------------------------------------------------------------
# Scene helpers
# --------------------------------------------------------------------------
def collection(name, parent):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


def remove_collection_tree(coll):
    for child in list(coll.children):
        remove_collection_tree(child)
    for ob in list(coll.objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
            elif isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
    bpy.data.collections.remove(coll)


def mesh_object(name, bm, mat, coll, loc=(0, 0, 0), smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = abs(p.normal.z) < 0.99
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    if mat is not None:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _box_bm(sx, sy, sz, bm=None, offset=(0, 0, 0)):
    bm = bm or bmesh.new()
    res = bmesh.ops.create_cube(bm, size=1.0)
    for v in res["verts"]:
        v.co = Vector((v.co.x * sx + offset[0], v.co.y * sy + offset[1], v.co.z * sz + offset[2]))
    return bm


def box(name, x0, x1, y0, y1, z0, z1, mat, coll):
    """Axis-aligned box from min/max bounds; origin at its centre."""
    bm = _box_bm(x1 - x0, y1 - y0, z1 - z0)
    return mesh_object(name, bm, mat, coll, ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))


def sized_box(name, size, loc, mat, coll, rot=(0, 0, 0)):
    bm = _box_bm(*size)
    ob = mesh_object(name, bm, mat, coll, loc)
    ob.rotation_euler = rot
    return ob


def cylinder(name, r, depth, loc, mat, coll, rot=(0, 0, 0), r2=None, seg=32):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    ob = mesh_object(name, bm, mat, coll, loc, smooth=True)
    ob.rotation_euler = rot
    return ob


def sphere(name, r, loc, mat, coll, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=r)
    ob = mesh_object(name, bm, mat, coll, loc)
    for p in ob.data.polygons:
        p.use_smooth = True
    ob.scale = scale
    return ob


def apply_object_transform(ob):
    ob.data.transform(ob.matrix_basis)
    ob.matrix_basis = Matrix.Identity(4)


def boolean_cut(ob, cuts):
    """Subtract a set of shapes from `ob` and bake the result into its mesh.

    cuts: list of ("box", x0, x1, y0, y1, z0, z1) or
                  ("cyl", r, depth, (x, y, z), axis) with axis in "XYZ".
    """
    bm = bmesh.new()
    for c in cuts:
        if c[0] == "box":
            _, x0, x1, y0, y1, z0, z1 = c
            _box_bm(x1 - x0, y1 - y0, z1 - z0, bm,
                    ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
        else:
            _, r, depth, loc, axis = c
            rot = {"X": Matrix.Rotation(math.pi / 2, 4, "Y"),
                   "Y": Matrix.Rotation(math.pi / 2, 4, "X"),
                   "Z": Matrix.Identity(4)}[axis]
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32,
                                  radius1=r, radius2=r, depth=depth,
                                  matrix=Matrix.Translation(loc) @ rot)
    # Express the cutter in the target's local space.
    bm.transform(ob.matrix_world.inverted())
    cme = bpy.data.meshes.new("_cutter")
    bm.to_mesh(cme)
    bm.free()
    cutter = bpy.data.objects.new("_cutter", cme)
    cutter.matrix_world = ob.matrix_world.copy()
    bpy.context.scene.collection.objects.link(cutter)

    mod = ob.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    mod.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    new_me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    old = ob.data
    ob.data = new_me
    new_me.name = old.name
    bpy.data.meshes.remove(old)
    bpy.data.objects.remove(cutter, do_unlink=True)
    bpy.data.meshes.remove(cme)
    # Keep only the target's own material slot.
    while len(ob.data.materials) > 1:
        ob.data.materials.pop()
    for p in ob.data.polygons:
        p.material_index = 0
    return ob


def bevel(ob, width=0.012):
    m = ob.modifiers.new("Bevel", "BEVEL")
    m.width = width
    m.segments = 2
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(40)
    m.harden_normals = False
    return m


def catmull_rom(points, n=10):
    P = [Vector(p) for p in points]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n):
            t = k / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t
                              + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t))
    out.append(P[-2])
    return out


def tube(name, points, radius, mat, coll, smooth=False):
    """Sweep a round tube along a polyline (or a smoothed path) and bake it to a mesh."""
    pts = catmull_rom(points) if smooth else [Vector(p) for p in points]
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, v in zip(sp.points, pts):
        p.co = (v.x, v.y, v.z, 1.0)
    tmp = bpy.data.objects.new("_tube", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.curves.remove(cu)
    me.name = name
    for p in me.polygons:
        p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        me.materials.clear()
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob, pts


def arrow_head(name, tip, direction, radius, mat, coll):
    d = Vector(direction).normalized()
    depth = radius * 5
    ob = cylinder(name, radius * 2.4, depth, Vector(tip) - d * depth / 2, mat, coll, r2=0.0, seg=24)
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d)
    return ob


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
def srgb_to_linear(c):
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c)


def material(name, color, rough=0.8, metal=0.0, alpha=1.0, emit=0.0,
             transmission=0.0, bump=None):
    """Principled material. `bump` = (scale, strength, stretch_z) adds a
    procedural noise bump for renders; glTF keeps the flat base colour."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (-300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    rgba = (*srgb_to_linear(color), 1.0)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Alpha"].default_value = alpha
    if transmission:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if emit:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = emit
    if bump:
        scale, strength, stretch = bump
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1.0, 1.0, stretch)
        nz = nt.nodes.new("ShaderNodeTexNoise")
        nz.inputs["Scale"].default_value = scale
        nz.inputs["Detail"].default_value = 8.0
        bp = nt.nodes.new("ShaderNodeBump")
        bp.inputs["Strength"].default_value = strength
        bp.inputs["Distance"].default_value = 0.02
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
        nt.links.new(nz.outputs["Fac"], bp.inputs["Height"])
        nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    mat.diffuse_color = rgba
    if alpha < 1.0:
        for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            try:
                setattr(mat, attr, val)
                break
            except (AttributeError, TypeError):
                continue
    return mat


def make_materials():
    return {
        "earth": material("Rammed earth", (0.62, 0.44, 0.30), 0.95, bump=(6.0, 0.35, 8.0)),
        "plaster": material("Lime-gypsum plaster", (0.86, 0.78, 0.64), 0.9, bump=(14.0, 0.12, 1.0)),
        "clay": material("Clay thermal-mass lining", (0.66, 0.40, 0.26), 0.92, bump=(10.0, 0.25, 1.0)),
        "floor": material("Stone floor", (0.78, 0.72, 0.62), 0.6),
        "sand": material("Desert ground", (0.80, 0.66, 0.47), 1.0, bump=(3.0, 0.3, 1.0)),
        "timber": material("Reclaimed timber", (0.45, 0.30, 0.17), 0.7, bump=(3.0, 0.15, 30.0)),
        "fibre": material("Date-palm fibre pad (wet)", (0.50, 0.36, 0.18), 0.55, bump=(40.0, 0.8, 0.15)),
        "water": material("Greywater", (0.20, 0.55, 0.75), 0.05, alpha=0.7),
        "pvc": material("Feed pipe", (0.18, 0.40, 0.62), 0.4),
        "tank": material("Greywater tank", (0.16, 0.30, 0.48), 0.5),
        "absorber": material("Matte-black absorber", (0.02, 0.02, 0.025), 0.45, metal=0.6),
        "glass": material("Glazing", (0.80, 0.92, 0.98), 0.03, alpha=0.18, transmission=0.9),
        "alu": material("Aluminium", (0.80, 0.82, 0.84), 0.3, metal=1.0),
        "cell": material("Solar cell", (0.04, 0.08, 0.22), 0.15, metal=0.3),
        "fan": material("Fan plastic", (0.12, 0.12, 0.14), 0.5),
        "pcb": material("ESP32 board", (0.06, 0.35, 0.16), 0.5),
        "servo": material("Servo", (0.10, 0.25, 0.70), 0.5),
        "mesh": material("Fibreglass mesh", (0.15, 0.16, 0.17), 0.7, alpha=0.45),
        "fabric": material("Cushion fabric", (0.55, 0.16, 0.14), 0.95),
        "rug": material("Rug", (0.35, 0.18, 0.12), 1.0),
        "figure": material("Scale figure", (0.70, 0.70, 0.72), 0.8),
        "palm": material("Palm frond", (0.25, 0.42, 0.15), 0.8),
        "trunk": material("Palm trunk", (0.42, 0.32, 0.22), 0.95, bump=(8.0, 0.6, 6.0)),
        "cold": material("Airflow cool", (0.10, 0.45, 1.0), 0.4, emit=0.6),
        "hot": material("Airflow warm", (1.0, 0.32, 0.08), 0.4, emit=0.6),
        "wind": material("Airflow wind", (0.55, 0.75, 1.0), 0.4, emit=0.4),
    }


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def build_site(M, C):
    g = box("Ground", -200, 200, -200, 200, -0.30, -0.02, M["sand"], C)
    for i, (x, y, h) in enumerate([(8.0, 6.5, 5.5), (-6.0, 1.0, 6.5), (10.5, -1.0, 4.5)]):
        cylinder(f"Palm {i} trunk", 0.17, h, (x, y, h / 2), M["trunk"], C, r2=0.11, seg=12)
        for k in range(11):
            # Tapered leaf from the crown outwards, drooping with length
            L = 2.0 + 0.3 * math.sin(k * 2.1)
            bm = _box_bm(L, 0.36, 0.02, offset=(L / 2, 0, 0))
            for v in bm.verts:
                f = v.co.x / L
                v.co.y *= 1.0 - 0.85 * f
                v.co.z -= 0.35 * f * f
            fr = mesh_object(f"Palm {i} frond {k}", bm, M["palm"], C, (x, y, h - 0.05))
            fr.rotation_euler = (0, math.radians(-18 + 16 * (k % 3)), k / 11 * math.tau + i)
        sphere(f"Palm {i} crown", 0.16, (x, y, h - 0.1), M["trunk"], C)
    return g


def build_building(M, C, CUT):
    x0, x1, y0, y1 = -WALL, ROOM_X + WALL, -WALL, ROOM_Y + WALL
    box("Floor slab", x0, x1, y0, y1, -0.15, 0.0, M["floor"], C)

    west = box("Wall West", x0, 0, y0, y1, 0, ROOM_H, M["earth"], C)
    east = box("Wall East", ROOM_X, x1, y0, y1, 0, ROOM_H, M["earth"], C)
    north = box("Wall North", 0, ROOM_X, ROOM_Y, y1, 0, ROOM_H, M["earth"], C)
    south = box("Wall South (cutaway)", 0, ROOM_X, y0, 0, 0, ROOM_H, M["earth"], CUT)

    door = ("box", ROOM_X - 0.1, x1 + 0.1, 2.55, 3.45, -0.1, 2.10)
    win_n = ("box", 2.4, 3.6, ROOM_Y - 0.1, y1 + 0.1, 1.0, 2.0)
    win_s = ("box", 2.4, 3.6, y0 - 0.1, 0.1, 1.0, 2.0)
    boolean_cut(east, [door])
    boolean_cut(north, [win_n])
    boolean_cut(south, [win_s])
    for w in (west, east, north, south):
        bevel(w)

    roof = box("Roof slab", x0, x1, y0, y1, ROOM_H, ROOF_TOP, M["plaster"], C)
    boolean_cut(roof, [("box", IN_X0, IN_X1, SH_Y0, SH_Y1, ROOM_H - 0.1, ROOF_TOP + 0.1),
                       ("box", EX_X0, EX_X1, SH_Y0, SH_Y1, ROOM_H - 0.1, ROOF_TOP + 0.1)])
    bevel(roof)

    pz0, pz1, pt = ROOF_TOP, ROOF_TOP + PARAPET_H, 0.15
    for name, b, coll in (("Parapet West", (x0, x0 + pt, y0, y1), C),
                          ("Parapet East", (x1 - pt, x1, y0, y1), C),
                          ("Parapet North", (x0 + pt, x1 - pt, y1 - pt, y1), C),
                          ("Parapet South (cutaway)", (x0 + pt, x1 - pt, y0, y0 + pt), CUT)):
        bevel(box(name, *b, pz0, pz1, M["plaster"], coll), 0.008)

    # Door, windows
    box("Door", ROOM_X + 0.10, ROOM_X + 0.15, 2.56, 3.44, 0.0, 2.08, M["timber"], C)
    sized_box("Door handle", (0.04, 0.03, 0.12), (ROOM_X + 0.31, 2.65, 1.0), M["alu"], C)
    for tag, y, coll in (("North", ROOM_Y + WALL / 2, C), ("South", -WALL / 2, CUT)):
        box(f"Window {tag} glass", 2.42, 3.58, y - 0.008, y + 0.008, 1.02, 1.98, M["glass"], coll)
        for nm, b in (("sill", (2.36, 3.64, y - 0.2, y + 0.2, 0.94, 1.0)),
                      ("head", (2.40, 3.60, y - 0.04, y + 0.04, 1.96, 2.0)),
                      ("mullion", (2.98, 3.02, y - 0.04, y + 0.04, 1.0, 1.98))):
            box(f"Window {tag} {nm}", *b, M["timber"], coll)


def build_tower(M, C, CUT):
    z0, z1 = ROOF_TOP, TOWER_TOP
    west = box("Tower West wall", TW_X0, IN_X0, TW_Y0, TW_Y1, z0, z1, M["plaster"], C)
    east = box("Tower East wall", EX_X1, TW_X1, TW_Y0, TW_Y1, z0, z1, M["plaster"], C)
    north = box("Tower North wall", IN_X0, EX_X1, SH_Y1, TW_Y1, z0, z1, M["plaster"], C)
    south_in = box("Tower South wall, intake (cutaway)", IN_X0, EX_X0 - 0.03, TW_Y0, SH_Y0, z0, z1,
                   M["plaster"], CUT)
    south_ex = box("Tower South wall, exhaust", EX_X0 - 0.03, EX_X1, TW_Y0, SH_Y0, z0, z1, M["plaster"], C)

    open_w = ("box", TW_X0 - 0.1, IN_X0 + 0.01, SH_Y0, SH_Y1, OPEN_Z0, OPEN_Z1)
    open_e = ("box", EX_X1 - 0.01, TW_X1 + 0.1, SH_Y0, SH_Y1, OPEN_Z0, OPEN_Z1)
    boolean_cut(west, [open_w])
    boolean_cut(east, [open_e])
    # Solar-chimney window in the south face of the exhaust shaft
    boolean_cut(south_ex, [("box", EX_X0 + 0.06, EX_X1 - 0.06, TW_Y0 - 0.1, SH_Y0 + 0.1,
                            z0 + 0.20, OPEN_Z0 - 0.15)])
    # Traditional recessed panels on the north face
    boolean_cut(north, [("box", x, x + 0.16, TW_Y1 - 0.035, TW_Y1 + 0.1, z0 + 0.35, OPEN_Z0 - 0.2)
                        for x in (0.02, 0.33, 0.64, 0.95)])
    for w in (west, east, north, south_in, south_ex):
        bevel(w, 0.01)

    # Central divider: runs from the cap down to just above the floor, leaving
    # the low supply opening into the room.
    box("Tower divider", IN_X1, EX_X0, SH_Y0, SH_Y1, SUPPLY_H, z1, M["plaster"], C)

    # Cornice and cap
    bevel(box("Tower cornice", TW_X0 - 0.06, TW_X1 + 0.06, TW_Y0 - 0.06, TW_Y1 + 0.06,
              z1 - 0.12, z1, M["plaster"], C), 0.01)
    bevel(box("Tower cap", TW_X0 - 0.15, TW_X1 + 0.15, TW_Y0 - 0.15, TW_Y1 + 0.15,
              z1, z1 + 0.12, M["plaster"], C), 0.015)
    # Timber lintels over the openings (traditional detail)
    box("Lintel West", TW_X0 - 0.02, IN_X0, SH_Y0 - 0.08, SH_Y1 + 0.08, OPEN_Z1, OPEN_Z1 + 0.06, M["timber"], C)
    box("Lintel East", EX_X1, TW_X1 + 0.02, SH_Y0 - 0.08, SH_Y1 + 0.08, OPEN_Z1, OPEN_Z1 + 0.06, M["timber"], C)

    # Intake duct below the roof: carries the cooled air down to the floor.
    box("Duct side South (cutaway)", IN_X0, EX_X0, TW_Y0, SH_Y0, 0, ROOM_H, M["plaster"], CUT)
    box("Duct side North", IN_X0, EX_X0, SH_Y1, TW_Y1, 0, ROOM_H, M["plaster"], C)

    # Supply grille at the foot of the divider and exhaust grille in the ceiling
    gx = (IN_X1 + EX_X0) / 2
    for i in range(5):
        z = 0.06 + i * 0.08
        sized_box(f"Supply grille slat {i}", (0.05, SHAFT, 0.012), (gx, ROOM_Y / 2, z), M["timber"], C,
                  rot=(0, math.radians(-30), 0))
    for i in range(6):
        x = EX_X0 + 0.05 + i * 0.1
        box(f"Exhaust grille slat {i}", x, x + 0.015, SH_Y0, SH_Y1, ROOM_H - 0.04, ROOM_H, M["timber"], C)


def build_pad(M, C):
    """Upgrade 1: wet date-palm fibre pad behind the windward opening, fed by greywater."""
    box("Evaporative pad", IN_X0 + 0.01, IN_X0 + 0.09, SH_Y0 + 0.01, SH_Y1 - 0.01,
        OPEN_Z0 + 0.03, OPEN_Z1 - 0.03, M["fibre"], C)
    trough = box("Drip trough", IN_X0, IN_X0 + 0.11, SH_Y0, SH_Y1, OPEN_Z1 - 0.04, OPEN_Z1, M["pvc"], C)
    boolean_cut(trough, [("box", IN_X0 + 0.01, IN_X0 + 0.10, SH_Y0 + 0.01, SH_Y1 - 0.01,
                          OPEN_Z1 - 0.03, OPEN_Z1 + 0.1)])
    tray = box("Collection tray", IN_X0, IN_X0 + 0.13, SH_Y0, SH_Y1, OPEN_Z0 - 0.06, OPEN_Z0, M["pvc"], C)
    boolean_cut(tray, [("box", IN_X0 + 0.01, IN_X0 + 0.12, SH_Y0 + 0.01, SH_Y1 - 0.01,
                        OPEN_Z0 - 0.05, OPEN_Z0 + 0.1)])
    box("Tray water", IN_X0 + 0.012, IN_X0 + 0.118, SH_Y0 + 0.012, SH_Y1 - 0.012,
        OPEN_Z0 - 0.05, OPEN_Z0 - 0.025, M["water"], C)

    # Greywater tank + small solar pump at the foot of the west wall
    tx, ty = -1.0, 2.75
    cylinder("Greywater tank", 0.38, 1.0, (tx, ty, 0.5), M["tank"], C, seg=40)
    cylinder("Greywater tank lid", 0.16, 0.06, (tx, ty, 1.03), M["pvc"], C)
    sized_box("Pump", (0.22, 0.16, 0.16), (tx + 0.25, ty - 0.48, 0.08), M["pvc"], C)
    px = TW_X0 - WALL + T_WALL - 0.06          # just proud of the west wall (-0.36)
    tube("Feed pipe", [(tx + 0.25, ty - 0.48, 0.16), (tx + 0.25, ty - 0.48, 0.30),
                       (px, ty - 0.48, 0.30),
                       (px, 2.52, 0.30), (px, 2.52, OPEN_Z1 + 0.07),
                       (px, ROOM_Y / 2, OPEN_Z1 + 0.07), (IN_X0 + 0.05, ROOM_Y / 2, OPEN_Z1 + 0.07)],
         0.016, M["pvc"], C)
    for z in (1.0, 2.0, ROOF_TOP + 0.15):
        box(f"Pipe clip {z:.1f}", px - 0.03, -WALL, 2.49, 2.55, z, z + 0.03, M["alu"], C)


def build_chimney(M, C):
    """Upgrade 2: matte-black absorber behind glass on the sunny (south) face of the exhaust shaft."""
    cx0, cx1 = EX_X0 + 0.06, EX_X1 - 0.06
    cz0, cz1 = ROOF_TOP + 0.20, OPEN_Z0 - 0.15
    box("Chimney absorber", cx0, cx1, SH_Y0 - 0.02, SH_Y0, cz0, cz1, M["absorber"], C)
    gy = TW_Y0 - 0.02
    box("Chimney glazing", cx0, cx1, gy - 0.006, gy, cz0, cz1, M["glass"], C)
    f = 0.035
    for nm, b in (("bottom", (cx0 - f, cx1 + f, gy - 0.04, TW_Y0, cz0 - f, cz0)),
                  ("top", (cx0 - f, cx1 + f, gy - 0.04, TW_Y0, cz1, cz1 + f)),
                  ("left", (cx0 - f, cx0, gy - 0.04, TW_Y0, cz0, cz1)),
                  ("right", (cx1, cx1 + f, gy - 0.04, TW_Y0, cz0, cz1)),
                  ("glazing bar", ((cx0 + cx1) / 2 - 0.012, (cx0 + cx1) / 2 + 0.012, gy - 0.03, gy,
                                   cz0, cz1))):
        box(f"Chimney frame {nm}", *b, M["timber"], C)


def fan(name, loc, M, C):
    s, t = 0.14, 0.025
    frame = sized_box(f"{name} frame", (s, s, t), loc, M["fan"], C)
    boolean_cut(frame, [("cyl", 0.064, 0.1, loc, "Z")])
    cylinder(f"{name} hub", 0.022, t * 0.9, loc, M["fan"], C, seg=24)
    for k in range(7):
        a = k / 7 * math.tau
        b = sized_box(f"{name} blade {k}", (0.045, 0.022, 0.003),
                      (loc[0] + math.cos(a) * 0.042, loc[1] + math.sin(a) * 0.042, loc[2]),
                      M["fan"], C)
        b.rotation_mode = "ZYX"
        b.rotation_euler = Euler((math.radians(25), 0, a), "ZYX")


def build_fans(M, C):
    """Upgrade 3: three recycled 140 mm 12 V fans in the exhaust shaft, run by a 10 W panel."""
    zc = ROOM_H + 0.12
    plate = box("Fan mounting plate", EX_X0, EX_X1, SH_Y0, SH_Y1, zc - 0.01, zc + 0.01, M["timber"], C)
    xs = [EX_X0 + 0.10, (EX_X0 + EX_X1) / 2, EX_X1 - 0.10]
    boolean_cut(plate, [("cyl", 0.064, 0.1, (x, ROOM_Y / 2, zc), "Z") for x in xs])
    for i, x in enumerate(xs):
        fan(f"Solar fan {i + 1}", (x, ROOM_Y / 2, zc + 0.023), M, C)

    # 10 W panel (~0.42 x 0.30 m) on the cap, tilted 25 degrees to the south
    cap_top = TOWER_TOP + 0.12
    pw, pd, tilt = 0.42, 0.30, math.radians(25)
    ctr = Vector(((TW_X0 + TW_X1) / 2, ROOM_Y / 2, cap_top + 0.20))
    rot = Euler((tilt, 0, 0))
    parts = [sized_box("Solar panel backsheet", (pw, pd, 0.025), (0, 0, 0), M["alu"], C)]
    for i in range(6):
        for j in range(4):
            parts.append(sized_box(f"Solar cell {i}-{j}", (pw / 6 - 0.008, pd / 4 - 0.008, 0.004),
                                   (-pw / 2 + (i + 0.5) * pw / 6, -pd / 2 + (j + 0.5) * pd / 4, 0.0135),
                                   M["cell"], C))
    for p in parts:
        p.location = ctr + rot.to_matrix() @ p.location
        p.rotation_euler = rot
    for dx in (-0.15, 0.15):
        for dy, h in ((-0.10, 0.20 - 0.10 * math.sin(tilt)), (0.10, 0.20 + 0.10 * math.sin(tilt))):
            cylinder("Panel leg", 0.012, h, (ctr.x + dx, ctr.y + dy * math.cos(tilt), cap_top + h / 2),
                     M["alu"], C, seg=12)
    tube("Panel cable", [(ctr.x + 0.22, ctr.y, cap_top + 0.05), (TW_X1 + 0.02, ctr.y + 0.3, cap_top),
                         (TW_X1 + 0.02, ctr.y + 0.3, OPEN_Z1 + 0.15),
                         (EX_X1, ctr.y + 0.3, OPEN_Z1 + 0.15)], 0.006, M["fan"], C)


def build_louvers(M, C):
    """Upgrade 4: servo-driven timber louvers in both openings, run by an ESP32."""
    n = 6
    pitch = (OPEN_Z1 - OPEN_Z0) / n
    for side, xc, sign in (("West", (TW_X0 + IN_X0) / 2, -1), ("East", (EX_X1 + TW_X1) / 2, 1)):
        for i in range(n):
            z = OPEN_Z0 + (i + 0.5) * pitch
            sized_box(f"Louver {side} {i + 1}", (0.13, SHAFT - 0.01, 0.014), (xc, ROOM_Y / 2, z), M["timber"], C,
                      rot=(0, math.radians(35) * sign, 0))
        cylinder(f"Louver {side} pivot rod", 0.006, SHAFT, (xc, ROOM_Y / 2, OPEN_Z0 + 0.5 * pitch), M["alu"], C,
                 rot=(math.pi / 2, 0, 0), seg=10)
        sized_box(f"Servo {side}", (0.04, 0.022, 0.04), (xc, SH_Y1 - 0.02, OPEN_Z0 + 0.03), M["servo"], C)
        sized_box(f"Louver {side} linkage", (0.008, 0.008, OPEN_Z1 - OPEN_Z0 - 0.1),
                  (xc + 0.055 * sign, SH_Y1 - 0.01, (OPEN_Z0 + OPEN_Z1) / 2), M["alu"], C)

    # Controller on the room face of the intake duct
    x = EX_X0
    box("ESP32 enclosure", x, x + 0.035, 1.90, 2.12, 1.45, 1.60, M["pcb"], C)
    box("Temp-humidity sensor", x, x + 0.02, 2.16, 2.20, 1.50, 1.55, M["alu"], C)


def build_mesh(M, C):
    """Upgrade 5: recycled fibreglass insect & dust mesh behind each louver bank."""
    box("Mesh West", IN_X0 - 0.006, IN_X0, SH_Y0, SH_Y1, OPEN_Z0, OPEN_Z1, M["mesh"], C)
    box("Mesh East", EX_X1, EX_X1 + 0.006, SH_Y0, SH_Y1, OPEN_Z0, OPEN_Z1, M["mesh"], C)


def build_mass(M, C, CUT):
    """Upgrade 6: clay plaster lining on the inner wall faces (time constant 2.5 h -> 10 h)."""
    L = LINING
    west = box("Lining West", 0, L, 0, ROOM_Y, 0, ROOM_H, M["clay"], C)
    east = box("Lining East", ROOM_X - L, ROOM_X, 0, ROOM_Y, 0, ROOM_H, M["clay"], C)
    north = box("Lining North", L, ROOM_X - L, ROOM_Y - L, ROOM_Y, 0, ROOM_H, M["clay"], C)
    south = box("Lining South (cutaway)", L, ROOM_X - L, 0, L, 0, ROOM_H, M["clay"], CUT)
    boolean_cut(east, [("box", ROOM_X - 0.2, ROOM_X + 0.1, 2.55, 3.45, -0.1, 2.10)])
    boolean_cut(north, [("box", 2.4, 3.6, ROOM_Y - 0.2, ROOM_Y + 0.1, 1.0, 2.0)])
    boolean_cut(south, [("box", 2.4, 3.6, -0.1, 0.2, 1.0, 2.0)])
    box("Lining Ceiling", L, ROOM_X - L, L, ROOM_Y - L, ROOM_H - 0.001, ROOM_H, M["clay"], C)


def build_interior(M, C):
    box("Rug", 1.6, 4.4, 0.8, 3.2, 0.0, 0.012, M["rug"], C)
    box("Floor cushion", 1.5, 4.5, ROOM_Y - 0.65, ROOM_Y - 0.06, 0.0, 0.32, M["fabric"], C)
    box("Back cushion", 1.5, 4.5, ROOM_Y - 0.2, ROOM_Y - 0.06, 0.32, 0.75, M["fabric"], C)
    box("Low table top", 2.5, 3.5, 1.7, 2.4, 0.38, 0.42, M["timber"], C)
    for x in (2.55, 3.45):
        for y in (1.75, 2.35):
            box("Table leg", x - 0.025, x + 0.025, y - 0.025, y + 0.025, 0.0, 0.38, M["timber"], C)
    # 1.75 m scale figure
    fx, fy = 3.9, 2.85
    cylinder("Figure legs", 0.14, 0.85, (fx, fy, 0.425), M["figure"], C, r2=0.16)
    cylinder("Figure torso", 0.17, 0.62, (fx, fy, 1.16), M["figure"], C, r2=0.2)
    sphere("Figure head", 0.115, (fx, fy, 1.62), M["figure"], C, scale=(0.9, 0.95, 1.1))


def build_airflow(M, C):
    """Diagrammatic airflow: wind in, cooled supply down the intake, warm exhaust up and out."""
    r = 0.035
    y = ROOM_Y / 2
    for i, z in enumerate((5.15, 5.4, 5.65)):
        _, pts = tube(f"Wind streak {i}", [(-3.6, y + (i - 1) * 0.2, z), (-0.5, y + (i - 1) * 0.1, z)], 0.02,
                      M["wind"], C)
        arrow_head(f"Wind streak {i} head", pts[-1] + Vector((0.12, 0, 0)), (1, 0, 0), 0.02, M["wind"], C)
    cold = [(-0.4, y, 5.4), (0.25, y, 5.35), (0.30, y, 4.3), (0.30, y, 1.2), (0.35, y, 0.35),
            (0.95, y, 0.22), (2.0, y, 0.3), (3.2, y, 0.65), (4.2, y, 1.4)]
    _, pts = tube("Airflow cool supply", cold, r, M["cold"], C, smooth=True)
    arrow_head("Airflow cool supply head", pts[-1], pts[-1] - pts[-4], r, M["cold"], C)
    warm = [(4.45, y, 1.75), (4.4, y, 2.45), (3.4, y, 2.75), (1.6, y, 2.75), (1.0, y, 2.9),
            (0.96, y, 3.6), (0.96, y, 5.0), (1.2, y, 5.42), (2.0, y, 5.55), (3.2, y, 5.8)]
    _, pts = tube("Airflow warm exhaust", warm, r, M["hot"], C, smooth=True)
    arrow_head("Airflow warm exhaust head", pts[-1], pts[-1] - pts[-4], r, M["hot"], C)


def build_cameras_lights(C):
    scene = bpy.context.scene
    sun_d = bpy.data.lights.new("Sun", "SUN")
    sun_d.energy = 4.5
    sun_d.angle = math.radians(1.2)
    sun = bpy.data.objects.new("Sun", sun_d)
    C.objects.link(sun)
    s = Vector((-0.45, -0.75, 0.85)).normalized()
    sun.rotation_euler = (-s).to_track_quat("-Z", "Y").to_euler()

    cams = {}
    for name, loc, tgt, lens in (
        ("Camera Exterior", (12.0, -11.0, 6.5), (1.8, 1.8, 3.1), 35),
        ("Camera Section", (1.6, -10.5, 3.3), (1.6, 2.0, 2.9), 30),
        ("Camera Tower detail", (-3.0, -3.2, 6.6), (0.55, 2.0, 5.15), 45),
    ):
        cd = bpy.data.cameras.new(name)
        cd.lens = lens
        cam = bpy.data.objects.new(name, cd)
        cam.location = loc
        look_at(cam, tgt)
        C.objects.link(cam)
        cams[name] = cam
    scene.camera = cams["Camera Exterior"]

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (*srgb_to_linear((0.62, 0.76, 0.93)), 1.0)
        bg.inputs["Strength"].default_value = 0.9
    return cams


README = """EcoCatcher 3D model
====================
Collections (toggle the eye / camera icons in the Outliner):
  Building ............ earth walls, roof, parapet, door, windows
  Tower ............... two-shaft windcatcher, 3 m above the roof
  1 Evaporative pad ... wet fibre pad, drip trough, tray, greywater tank + pump
  2 Solar chimney ..... black absorber behind glass on the sunny face
  3 Solar fans ........ 3 x 140 mm fans + 10 W panel on the cap
  4 Smart louvers ..... servo louvers both sides + ESP32 controller
  5 Mesh .............. insect & dust mesh behind the louvers
  6 Thermal mass ...... clay lining on the inner wall faces
  Interior ............ furniture and a 1.75 m scale figure
  Airflow ............. blue = cooled supply, orange = warm exhaust
  Cutaway ............. hide this to see the section through the room + intake

Cameras: Exterior, Section (hide Cutaway first), Tower detail.
Units: metres. Wind from -X (west); sun to the south (-Y).
Rebuild: run ecocatcher_model.py from the Scripting workspace.
"""


def build():
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"

    old = bpy.data.collections.get(ROOT)
    if old:
        remove_collection_tree(old)
    root = bpy.data.collections.new(ROOT)
    scene.collection.children.link(root)

    M = make_materials()
    cols = {k: collection(k, root) for k in (
        "Site", "Building", "Tower", "1 Evaporative pad", "2 Solar chimney", "3 Solar fans",
        "4 Smart louvers", "5 Insect & dust mesh", "6 Thermal-mass lining", "Interior",
        "Airflow", "Cutaway (hide for section view)", "Cameras & lights")}
    CUT = cols["Cutaway (hide for section view)"]

    build_site(M, cols["Site"])
    build_building(M, cols["Building"], CUT)
    build_tower(M, cols["Tower"], CUT)
    build_pad(M, cols["1 Evaporative pad"])
    build_chimney(M, cols["2 Solar chimney"])
    build_fans(M, cols["3 Solar fans"])
    build_louvers(M, cols["4 Smart louvers"])
    build_mesh(M, cols["5 Insect & dust mesh"])
    build_mass(M, cols["6 Thermal-mass lining"], CUT)
    build_interior(M, cols["Interior"])
    build_airflow(M, cols["Airflow"])
    build_cameras_lights(cols["Cameras & lights"])

    txt = bpy.data.texts.get("EcoCatcher README") or bpy.data.texts.new("EcoCatcher README")
    txt.clear()
    txt.write(README)
    return root, cols


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def set_visible(coll, visible):
    coll.hide_render = not visible
    lc = _layer_collection(bpy.context.view_layer.layer_collection, coll.name)
    if lc:
        lc.exclude = False
        lc.hide_viewport = not visible


def _layer_collection(lc, name):
    if lc.collection.name == name:
        return lc
    for ch in lc.children:
        found = _layer_collection(ch, name)
        if found:
            return found
    return None


def render_views(cols, outdir, samples):
    scene = bpy.context.scene
    os.makedirs(outdir, exist_ok=True)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    cut, air = cols["Cutaway (hide for section view)"], cols["Airflow"]
    cams = {o.name: o for o in cols["Cameras & lights"].objects if o.type == "CAMERA"}
    for fname, cam, show_cut, show_air in (
        ("ecocatcher_exterior.png", "Camera Exterior", True, False),
        ("ecocatcher_section.png", "Camera Section", False, True),
        ("ecocatcher_tower_detail.png", "Camera Tower detail", True, False),
    ):
        set_visible(cut, show_cut)
        set_visible(air, show_air)
        scene.camera = cams[cam]
        scene.render.filepath = os.path.join(outdir, fname)
        bpy.ops.render.render(write_still=True)
        print("rendered", scene.render.filepath)
    set_visible(cut, True)
    set_visible(air, True)
    scene.camera = cams["Camera Exterior"]


def export_glb(root, path):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in root.all_objects:
        if ob.type == "MESH":
            ob.select_set(True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True,
                              export_apply=True, export_cameras=False, export_lights=False)
    print("exported", path)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else (
        sys.argv[1:] if bpy.app.background and not sys.argv[0].endswith("blender") else [])
    ap = argparse.ArgumentParser(description="Build the EcoCatcher windcatcher model.")
    ap.add_argument("--blend", help="save the .blend file here")
    ap.add_argument("--glb", help="export a binary glTF here")
    ap.add_argument("--render", help="render preview PNGs into this folder")
    ap.add_argument("--samples", type=int, default=96)
    args, _ = ap.parse_known_args(argv)

    if bpy.app.background:
        # Fresh headless session: drop the factory-startup cube, light and camera.
        for name in ("Cube", "Light", "Camera"):
            ob = bpy.data.objects.get(name)
            if ob:
                bpy.data.objects.remove(ob, do_unlink=True)
    root, cols = build()
    if args.glb:
        export_glb(root, os.path.abspath(args.glb))
    if args.render:
        render_views(cols, os.path.abspath(args.render), args.samples)
    if args.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.blend))
        print("saved", args.blend)


if __name__ == "__main__":
    main()
