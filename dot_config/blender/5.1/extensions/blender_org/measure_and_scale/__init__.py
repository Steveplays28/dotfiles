# Copyright (C) 2025 Belaid Ziane

# ***** BEGIN GPL LICENSE BLOCK ****
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>
#
# ***** END GPL LICENSE BLOCK ***** 

bl_info = {
    "name": "Measure and Scale",
    "author": "Bill3D(Belaid Ziane)",
    "version": (1, 1, 6),
    "blender": (4, 2, 0),
    "location": "View3D > UI > Npanel > Item > Measure and Scale",
    "description": "Interactively measure between two points, scale the object uniformly to a target dimension with axis locking.",
    "category": "Object",
}
import bpy
import bmesh
import gpu
import blf
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree
from bpy.types import Operator, Panel, PropertyGroup, Scene
from bpy.props import (
    FloatProperty, StringProperty, PointerProperty, EnumProperty,
    FloatVectorProperty, BoolProperty
)
import bpy_extras.view3d_utils
from gpu_extras.batch import batch_for_shader

# Screen-space distances for snapping feedback
VERTEX_SNAP_DISTANCE_SCREEN = 15.0
MIDPOINT_SNAP_DISTANCE_SCREEN = 15.0
EDGE_SNAP_DISTANCE_SCREEN = 25.0

SNAP_POINT_SIZE = 10.0
CROSSHAIR_SIZE = 15.0
SUBTLE_INDICATOR_SIZE_FACTOR = 0.7

class ScaleInteractiveSettings(PropertyGroup):
    metric_unit: EnumProperty(
        name="Metric Unit",
        items=[('M', "m", "Meters"), ('CM', "cm", "Centimeters"), ('MM', "mm", "Millimeters")],
        default='M',
        description="Select the metric unit for display"
    )
    system_unit: EnumProperty(
        name="System",
        items=[('METRIC', "Metric", "Use Metric units"), ('IMPERIAL_FT', "ft", "Use Imperial units (Feet)"), ('IMPERIAL_IN', "in", "Use Imperial units (Inches)")],
        default='METRIC',
        description="Select the unit system for display"
    )
    decimal_precision: EnumProperty(
        name="Precision",
        items=[('0', "0", "0"), ('1', "0.0", "1"), ('2', "0.00", "2"), ('3', "0.000", "3"), ('4', "0.0000", "4")],
        default='2',
        description="Set the number of decimal places to display"
    )

def get_unit_suffix(settings):
    if settings.system_unit == 'METRIC': return settings.metric_unit.lower()
    if settings.system_unit == 'IMPERIAL_FT': return 'ft'
    if settings.system_unit == 'IMPERIAL_IN': return 'in'
    return ''

def convert_to_display_unit(value_meters, settings):
    if settings.system_unit == 'METRIC':
        if settings.metric_unit == 'CM': return value_meters * 100.0
        if settings.metric_unit == 'MM': return value_meters * 1000.0
    elif settings.system_unit == 'IMPERIAL_FT': return value_meters * 3.28084
    elif settings.system_unit == 'IMPERIAL_IN': return value_meters * 39.3701
    return value_meters

def convert_from_display_unit(value_display, settings):
    if settings.system_unit == 'METRIC':
        if settings.metric_unit == 'CM': return value_display / 100.0
        if settings.metric_unit == 'MM': return value_display / 1000.0
    elif settings.system_unit == 'IMPERIAL_FT': return value_display / 3.28084
    elif settings.system_unit == 'IMPERIAL_IN': return value_display / 39.3701
    return value_display

def ray_cast(context, position):
    region = context.region
    region3D = context.space_data.region_3d
    if not region or not region3D: return False, None, None, -1, None, None, None
    view_point = bpy_extras.view3d_utils.region_2d_to_origin_3d(region, region3D, position)
    view_vector = bpy_extras.view3d_utils.region_2d_to_vector_3d(region, region3D, position)
    depsgraph = context.evaluated_depsgraph_get()
    return context.scene.ray_cast(depsgraph, view_point, view_vector) + (view_point,)

def find_nearest_vertex_or_edge_world(context, event, active_obj):
    mouse_pos = Vector((event.mouse_region_x, event.mouse_region_y))
    region = context.region
    rv3d = context.space_data.region_3d
    if not region or not rv3d: return None, None, None, None

    # 1. Get a list of all potential objects to snap to.
    target_objects = [obj for obj in context.scene.objects if obj.type == 'MESH' and obj.visible_get()]
    if not target_objects:
        return None, 'CURSOR', None, None

    # 2. Get a 3D point under the cursor to use as a search reference.
    # This will also serve as our fallback if no snaps are found.
    ray_result, ray_hit_loc, _, _, hit_obj_raw, _, view_point = ray_cast(context, mouse_pos)
    fallback_pos_3d = None
    if ray_result:
        fallback_pos_3d = ray_hit_loc
    else:
        view_vector = bpy_extras.view3d_utils.region_2d_to_vector_3d(region, rv3d, mouse_pos)
        depth = 10.0
        op = context.window_manager.operators.get('object.scale_to_dimension_interactive')
        if op and op.has_start_vertex:
            start_vec = Vector(op.start_vertex_co) - view_point
            depth = start_vec.dot(view_vector)
            if depth < 0.1: depth = 10.0
        fallback_pos_3d = view_point + view_vector * depth

    # 3. Iterate through ALL target objects to find the best possible snap point.
    best_vertex_snap = None
    best_midpoint_snap = None
    best_edge_snap = None
    view_vector = rv3d.view_rotation @ Vector((0, 0, -1))

    for obj in target_objects:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        kd = KDTree(len(bm.verts))
        for i, v in enumerate(bm.verts): kd.insert(v.co, i)
        kd.balance()

        world_mat = obj.matrix_world
        world_mat_inv = world_mat.inverted_safe()
        local_search_center = world_mat_inv @ fallback_pos_3d

        NUM_CANDIDATE_NEIGHBORS = 40
        initial_candidates = [bm.verts[index] for _, index, _ in kd.find_n(local_search_center, NUM_CANDIDATE_NEIGHBORS)]
        
        # Consider a vertex "visible" if it's loose (no faces) or attached to a visible face.
        visible_verts = set()
        for vert in initial_candidates:
            # If the vertex has no linked faces, it's loose geometry and considered visible.
            if not vert.link_faces:
                visible_verts.add(vert)
                continue

            # Otherwise, check if any linked face is visible.
            for face in vert.link_faces:
                world_normal = (world_mat_inv.transposed() @ face.normal).normalized()
                if world_normal.dot(view_vector) < 0:
                    visible_verts.add(vert)
                    break  # Found a visible face, no need to check others for this vert

        visible_edges = set()
        for vert in visible_verts:
            for edge in vert.link_edges:
                if edge.verts[0] in visible_verts and edge.verts[1] in visible_verts:
                    visible_edges.add(edge)
        
        # Check this object's verts
        for vert in visible_verts:
            try:
                screen_co = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, world_mat @ vert.co)
                if screen_co:
                    dist_sq = (screen_co - mouse_pos).length_squared
                    if dist_sq < VERTEX_SNAP_DISTANCE_SCREEN**2:
                        if best_vertex_snap is None or dist_sq < best_vertex_snap[0]:
                            best_vertex_snap = (dist_sq, world_mat @ vert.co, obj)
            except (TypeError, ReferenceError): continue

        # Check this object's edges
        for edge in visible_edges:
            v0_co, v1_co = (world_mat @ v.co for v in edge.verts)
            try:
                s_v0 = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, v0_co)
                s_v1 = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, v1_co)
            except (TypeError, ReferenceError): continue
            if not (s_v0 and s_v1): continue

            # Midpoint
            midpoint_co = (v0_co + v1_co) / 2.0
            try:
                s_mid = bpy_extras.view3d_utils.location_3d_to_region_2d(region, rv3d, midpoint_co)
                if s_mid:
                    dist_sq_mid = (s_mid - mouse_pos).length_squared
                    if dist_sq_mid < MIDPOINT_SNAP_DISTANCE_SCREEN**2:
                        if best_midpoint_snap is None or dist_sq_mid < best_midpoint_snap[0]:
                            best_midpoint_snap = (dist_sq_mid, midpoint_co, obj)
            except (TypeError, ReferenceError): pass
            
            # Edge
            edge_vec_sq_len = (s_v1 - s_v0).length_squared
            if edge_vec_sq_len > 1e-6:
                t = max(0.0, min(1.0, (mouse_pos - s_v0).dot(s_v1 - s_v0) / edge_vec_sq_len))
                dist_sq_edge = (s_v0.lerp(s_v1, t) - mouse_pos).length_squared
                if dist_sq_edge < EDGE_SNAP_DISTANCE_SCREEN**2:
                    if best_edge_snap is None or dist_sq_edge < best_edge_snap[0]:
                        best_edge_snap = (dist_sq_edge, v0_co.lerp(v1_co, t), obj)

        bm.free()

    # 4. Now, evaluate the best snap found across all objects, respecting priority.
    if best_vertex_snap:
        return best_vertex_snap[1], 'VERTEX', fallback_pos_3d, best_vertex_snap[2]
    if best_midpoint_snap:
        return best_midpoint_snap[1], 'EDGE_MIDPOINT', fallback_pos_3d, best_midpoint_snap[2]
    if best_edge_snap:
        return best_edge_snap[1], 'EDGE', fallback_pos_3d, best_edge_snap[2]
    
    # 5. If no snap was found on any object, return the fallback cursor position.
    return fallback_pos_3d, 'CURSOR', ray_hit_loc, hit_obj_raw

def project_point_onto_axis(origin, point, axis_lock):
    origin_vec, point_vec = Vector(origin), Vector(point)
    if axis_lock == 'X': return origin_vec + Vector(((point_vec - origin_vec).x, 0.0, 0.0))
    if axis_lock == 'Y': return origin_vec + Vector((0.0, (point_vec - origin_vec).y, 0.0))
    if axis_lock == 'Z': return origin_vec + Vector((0.0, 0.0, (point_vec - origin_vec).z))
    return point_vec

def draw_callback_px(op, context):
    if not context.area or not op: return
    settings = context.scene.scale_interactive_settings
    font_id = 0
    blf.size(font_id, 14)
    precision = int(settings.decimal_precision)
    
    start_co = op.start_vertex_co if op.has_start_vertex else None
    end_co = op.end_vertex_co if op.has_end_vertex else None
    
    raw_hover_co = op._raw_hover_co
    projected_hover_co = op._hover_vertex_co
    
    raw_snap_type = op._hover_snap_type
    axis_lock = op._axis_lock
    rv3d = context.space_data.region_3d
    if not rv3d: return
    
    def to_2d(p):
        if p is None: return None
        try: return bpy_extras.view3d_utils.location_3d_to_region_2d(context.region, rv3d, p)
        except (TypeError, ReferenceError, AttributeError): return None

    screen_start_co = to_2d(start_co)
    screen_end_co = to_2d(end_co)
    screen_raw_hover_co = to_2d(raw_hover_co)
    screen_projected_hover_co = to_2d(projected_hover_co)
    
    # Ensure we have valid 2D coordinates before attempting to draw
    if screen_projected_hover_co is None and screen_start_co is None and screen_end_co is None:
        return
    
    # Get shader for each draw call to ensure Vulkan compatibility
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    
    # Save current GPU state
    depth_test_state = gpu.state.depth_test_get()
    blend_state = gpu.state.blend_get()
    line_width_state = gpu.state.line_width_get()
    
    try:
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('ALPHA')

        def get_indicator_colors(snap_type):
            if snap_type == 'VERTEX': return (0.0, 1.0, 0.0, 1.0), (0.0, 1.0, 0.0, 0.5)
            if snap_type == 'EDGE_MIDPOINT': return (0.0, 0.5, 1.0, 1.0), (0.0, 0.5, 1.0, 0.5)
            if snap_type == 'EDGE': return (1.0, 1.0, 0.0, 1.0), (1.0, 1.0, 0.0, 0.5)
            return (0.8, 0.8, 0.8, 1.0), (0.8, 0.8, 0.8, 0.5)

        def draw_snap_point(pos_2d, color, size, snap_type):
            # Create fresh shader instance for each draw call for Vulkan compatibility
            try:
                local_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                
                if snap_type == 'EDGE':
                    # Draw crosshair for edge snapping with enhanced visibility
                    points = [
                        (pos_2d[0] - size/2, pos_2d[1]), (pos_2d[0] + size/2, pos_2d[1]),
                        (pos_2d[0], pos_2d[1] - size/2), (pos_2d[0], pos_2d[1] + size/2)
                    ]
                    batch = batch_for_shader(local_shader, 'LINES', {"pos": points})
                    gpu.state.line_width_set(3.0)  # Increased from 2.0 for better Vulkan visibility
                    with gpu.matrix.push_pop():
                        local_shader.bind()
                        local_shader.uniform_float("color", color)
                        batch.draw(local_shader)
                        # Add a second crosshair with slight offset for better visibility
                        offset_color = (color[0], color[1], color[2], color[3] * 0.6)
                        local_shader.uniform_float("color", offset_color)
                        offset_points = [
                            (pos_2d[0] - size/2 + 1, pos_2d[1]), (pos_2d[0] + size/2 + 1, pos_2d[1]),
                            (pos_2d[0] + 1, pos_2d[1] - size/2), (pos_2d[0] + 1, pos_2d[1] + size/2)
                        ]
                        offset_batch = batch_for_shader(local_shader, 'LINES', {"pos": offset_points})
                        offset_batch.draw(local_shader)
                    gpu.state.line_width_set(line_width_state)
                else:
                    # Draw point for vertex/midpoint snapping
                    # Use a small quad instead of points for better Vulkan compatibility
                    half_size = size / 2.0
                    quad_points = [
                        (pos_2d[0] - half_size, pos_2d[1] - half_size),
                        (pos_2d[0] + half_size, pos_2d[1] - half_size),
                        (pos_2d[0] + half_size, pos_2d[1] + half_size),
                        (pos_2d[0] - half_size, pos_2d[1] + half_size)
                    ]
                    indices = [(0, 1, 2), (0, 2, 3)]  # Two triangles to form a quad
                    batch = batch_for_shader(local_shader, 'TRIS', {"pos": quad_points}, indices=indices)
                    with gpu.matrix.push_pop():
                        local_shader.bind()
                        local_shader.uniform_float("color", color)
                        batch.draw(local_shader)
            except Exception as e:
                # Fallback for any shader issues
                print(f"Shader error in draw_snap_point: {e}")
            
        # Helper to select the correct base size for the snap indicator
        def get_base_size(snap_type):
            return CROSSHAIR_SIZE if snap_type == 'EDGE' else SNAP_POINT_SIZE

        if screen_projected_hover_co and not end_co:
            base_color, subtle_color = get_indicator_colors(raw_snap_type)
            is_locked_and_different = (axis_lock != 'NONE' and screen_raw_hover_co and screen_raw_hover_co != screen_projected_hover_co)
            
            if is_locked_and_different:
                subtle_size = get_base_size(raw_snap_type) * SUBTLE_INDICATOR_SIZE_FACTOR
                draw_snap_point(screen_raw_hover_co, subtle_color, subtle_size, raw_snap_type)
            
            draw_snap_point(screen_projected_hover_co, base_color, get_base_size(raw_snap_type), raw_snap_type)

            if is_locked_and_different:
                gpu.state.line_width_set(2.0)  # Increased from 1.0 for better Vulkan visibility
                try:
                    line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                    batch = batch_for_shader(line_shader, 'LINES', {"pos": [screen_raw_hover_co, screen_projected_hover_co]})
                    with gpu.matrix.push_pop():
                        line_shader.bind()
                        line_shader.uniform_float("color", (0.7, 0.7, 0.7, 0.8))  # Slightly more opaque
                        batch.draw(line_shader)
                        # Add a second line with slight offset for better visibility in Vulkan
                        offset_color = (0.9, 0.9, 0.9, 0.4)
                        line_shader.uniform_float("color", offset_color)
                        offset_start = (screen_raw_hover_co[0] + 0.5, screen_raw_hover_co[1])
                        offset_end = (screen_projected_hover_co[0] + 0.5, screen_projected_hover_co[1])
                        offset_batch = batch_for_shader(line_shader, 'LINES', {"pos": [offset_start, offset_end]})
                        offset_batch.draw(line_shader)
                except Exception as e:
                    print(f"Shader error in axis lock line: {e}")
                gpu.state.line_width_set(line_width_state)

        if screen_start_co:
            base_color, _ = get_indicator_colors(op.start_snap_type)
            start_point_size = get_base_size(op.start_snap_type) + 2
            draw_snap_point(screen_start_co, base_color, start_point_size, op.start_snap_type)
        if screen_end_co:
            base_color, _ = get_indicator_colors(op.end_snap_type)
            end_point_size = get_base_size(op.end_snap_type) + 2
            draw_snap_point(screen_end_co, base_color, end_point_size, op.end_snap_type)

        line_drawn = False
        if screen_start_co:
            target_pos = screen_end_co or screen_projected_hover_co
            if target_pos:
                distance = op.measured_distance if end_co else (Vector(projected_hover_co) - Vector(start_co)).length if projected_hover_co else 0
                color = (0.53, 0.81, 0.92, 1.0) if end_co else (0.8, 0.8, 0.8, 0.9)
                if not end_co:
                    if axis_lock == 'X': color = (1.0, 0.0, 0.0, 0.9)
                    elif axis_lock == 'Y': color = (0.0, 1.0, 0.0, 0.9)
                    elif axis_lock == 'Z': color = (0.0, 0.0, 1.0, 0.9)
                
                # Enhanced line rendering for better Vulkan visibility
                line_width = 4.0 if end_co else 3.0
                gpu.state.line_width_set(line_width)
                try:
                    line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                    # For Vulkan, we'll draw the line multiple times with slight offsets for thickness
                    batch = batch_for_shader(line_shader, 'LINES', {"pos": [screen_start_co, target_pos]})
                    with gpu.matrix.push_pop():
                        line_shader.bind()
                        line_shader.uniform_float("color", color)
                        # Main line
                        batch.draw(line_shader)
                        # Add slight thickness by drawing additional lines with small offsets for Vulkan
                        # This ensures the line is visible regardless of backend
                        offset_color = (color[0], color[1], color[2], color[3] * 0.7)  # Slightly transparent
                        line_shader.uniform_float("color", offset_color)
                        for dx, dy in [(0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5)]:
                            offset_start = (screen_start_co[0] + dx, screen_start_co[1] + dy)
                            offset_end = (target_pos[0] + dx, target_pos[1] + dy)
                            offset_batch = batch_for_shader(line_shader, 'LINES', {"pos": [offset_start, offset_end]})
                            offset_batch.draw(line_shader)
                    line_drawn = True
                except Exception as e:
                    print(f"Shader error in measurement line: {e}")
                gpu.state.line_width_set(line_width_state)

                if distance > 1e-4:
                    text_pos = (Vector(screen_start_co) + Vector(target_pos)) / 2.0
                    display_dist = convert_to_display_unit(distance, settings)
                    unit_suffix = get_unit_suffix(settings)
                    
                    # --- ADDED: Check for rounding approximation ---
                    rounded_display = round(display_dist, precision)
                    high_precision_display = round(display_dist, precision + 2)
                    prefix = "~ " if abs(rounded_display - high_precision_display) > 1e-5 else ""

                    text = f"{prefix}{display_dist:.{precision}f} {unit_suffix}"
                    blf.position(font_id, text_pos.x + 10, text_pos.y + 10, 0)
                    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
                    blf.draw(font_id, text)

        blf.position(font_id, 20, 30, 0)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.draw(font_id, op.status_message)
        
    finally:
        # Restore GPU state
        gpu.state.depth_test_set(depth_test_state)
        gpu.state.blend_set(blend_state)
        gpu.state.line_width_set(line_width_state)
        gpu.state.point_size_set(1.0)  # Reset point size to default

class OBJECT_OT_ScaleToDimensionInteractive(Operator):
    bl_idname = "object.scale_to_dimension_interactive"
    bl_label = "Measure and Scale Interactive"
    bl_options = {'REGISTER', 'UNDO'}

    # Properties exposed to Blender
    start_vertex_co: FloatVectorProperty(name="Start Point", size=3, subtype='XYZ', unit='LENGTH')
    end_vertex_co: FloatVectorProperty(name="End Point", size=3, subtype='XYZ', unit='LENGTH')
    measured_distance: FloatProperty(name="Measured Distance", default=0.0, unit='LENGTH')
    selected_object_names: StringProperty()
    original_mode: StringProperty()
    status_message: StringProperty(default="Click first point (ESC to cancel)")
    has_start_vertex: BoolProperty(default=False)
    has_end_vertex: BoolProperty(default=False)
    start_snap_type: StringProperty(default="VERTEX")
    end_snap_type: StringProperty(default="VERTEX")
    
    # Use a class variable to track dialog success
    _dialog_success: BoolProperty(default=False)

    # Internal state variables
    _draw_handle = None
    _shader = None
    _hover_vertex_co = None
    _raw_hover_co = None
    _hover_snap_type = None
    _axis_lock = 'NONE'
    _original_wireframe_state = None
    _wireframe_changed_by_op = False
    _timer = None

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and obj.select_get() for obj in context.scene.objects) and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Active space must be a 3D View")
            return {'CANCELLED'}
        if OBJECT_OT_ScaleToDimensionInteractive._draw_handle is not None:
            self.report({'WARNING'}, "Interactive scale operation might already be in progress.")
            self._cleanup(context)
            return {'CANCELLED'}

        self.selected_object_names = ",".join(obj.name for obj in context.selected_objects if obj.type == 'MESH')
        if not self.selected_object_names:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        # Initialize internal state
        self.original_mode = context.mode
        self.has_start_vertex = False
        self.has_end_vertex = False
        self._dialog_success = False
        self._hover_vertex_co = None
        self._raw_hover_co = None
        self._hover_snap_type = None
        self._axis_lock = 'NONE'
        self._original_wireframe_state = None
        self._wireframe_changed_by_op = False
        self._timer = None

        if context.space_data.overlay.show_wireframes is False:
            self._original_wireframe_state = False
            context.space_data.overlay.show_wireframes = True
            self._wireframe_changed_by_op = True
        
        # Remove shader creation here as we'll create fresh shaders in draw callback for Vulkan compatibility
        self._shader = None
        OBJECT_OT_ScaleToDimensionInteractive._draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL')
        self._draw_handle = OBJECT_OT_ScaleToDimensionInteractive._draw_handle
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _update_hover_point(self, context, event):
        raw_snap_co, raw_snap_type, _, _ = find_nearest_vertex_or_edge_world(context, event, context.active_object)
        self._raw_hover_co = raw_snap_co
        self._hover_snap_type = raw_snap_type
        
        if raw_snap_co:
            self._hover_vertex_co = project_point_onto_axis(self.start_vertex_co, raw_snap_co, self._axis_lock) if self.has_start_vertex else raw_snap_co
        else:
            self._hover_vertex_co = None
        
        lock_status = f" (Locked to {self._axis_lock})" if self._axis_lock != 'NONE' else ""
        self.status_message = f"Click second point{lock_status} (ESC to cancel)" if self.has_start_vertex else "Click first point (ESC to cancel)"
        context.area.tag_redraw()

    def modal(self, context, event):
        if not context.area:
            return self._cancel_and_cleanup(context)

        # Handle the dialog completion/cancellation
        if self.has_end_vertex:
            # Check if dialog is still running
            dialog_active = any(o.bl_idname == OBJECT_OT_ScaleConfirmDialog.bl_idname 
                              for o in context.window_manager.operators)
            
            # If dialog is no longer active, clean up and finish
            if not dialog_active:
                self._cleanup(context)
                if self._dialog_success:
                    self.report({'INFO'}, "Interactive scaling finished.")
                    return {'FINISHED'}
                else:
                    self.report({'INFO'}, "Interactive scaling cancelled.")
                    return {'CANCELLED'}
            
            # Dialog is still active, pass through events to it
            return {'PASS_THROUGH'}

        # Handle mouse movement for hover updates
        if event.type == 'MOUSEMOVE':
            self._update_hover_point(context, event)

        # Handle left mouse clicks for point selection
        elif event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._hover_vertex_co:
                if not self.has_start_vertex:
                    self.start_vertex_co = self._hover_vertex_co
                    self.start_snap_type = self._hover_snap_type
                    self.has_start_vertex = True
                    self._hover_vertex_co = None
                    self._raw_hover_co = None
                    self.status_message = "Click second point (ESC to cancel)"
                else:
                    if (Vector(self._hover_vertex_co) - Vector(self.start_vertex_co)).length < 1e-4:
                        self.report({'INFO'}, "Second point too close to the first.")
                        return {'RUNNING_MODAL'}
                    self.end_vertex_co = self._hover_vertex_co
                    self.end_snap_type = self._hover_snap_type
                    self.measured_distance = (Vector(self.end_vertex_co) - Vector(self.start_vertex_co)).length
                    self.status_message = "Dialog Open - Enter Target Dimension"
                    self.has_end_vertex = True
                    
                    bpy.ops.object.scale_confirm_dialog('INVOKE_DEFAULT', 
                                                       measured_distance=self.measured_distance, 
                                                       selected_object_names=self.selected_object_names, 
                                                       original_mode=self.original_mode)
                    context.area.tag_redraw()
                    return {'RUNNING_MODAL'}
                context.area.tag_redraw()

        # Handle axis locking
        elif event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS' and self.has_start_vertex:
            self._axis_lock = event.type if self._axis_lock != event.type else 'NONE'
            self.report({'INFO'}, f"Axis lock {'set to ' + self._axis_lock if self._axis_lock != 'NONE' else 'removed'}.")
            self._update_hover_point(context, event)

        # Handle cancellation
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self.report({'INFO'}, "Interactive scaling cancelled.")
            return self._cancel_and_cleanup(context)

        # Pass through navigation and other events
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} or (event.type == 'MOUSEMOVE' and event.alt):
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        # Remove the timer if it exists
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        if self._draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
            OBJECT_OT_ScaleToDimensionInteractive._draw_handle = None
            self._draw_handle = None
        if self._wireframe_changed_by_op and self._original_wireframe_state is not None:
            if context and context.space_data:
                context.space_data.overlay.show_wireframes = self._original_wireframe_state
        if context and context.area:
            context.area.tag_redraw()

    def _cancel_and_cleanup(self, context):
        self._cleanup(context)
        return {'CANCELLED'}

class OBJECT_OT_ScaleConfirmDialog(Operator):
    bl_idname = "object.scale_confirm_dialog"
    bl_label = "Set Target Dimension"
    bl_options = {'REGISTER', 'INTERNAL'}
    
    measured_distance: FloatProperty(options={'HIDDEN'})
    selected_object_names: StringProperty(options={'HIDDEN'})
    original_mode: StringProperty(options={'HIDDEN'})
    target_dimension: FloatProperty(name="Target Dimension", description="Desired dimension in selected units", default=1.0, min=1e-5, soft_min=0.01)

    def invoke(self, context, event):
        # Find the main interactive operator and set its success flag
        interactive_op = next((o for o in context.window_manager.operators if o.bl_idname == OBJECT_OT_ScaleToDimensionInteractive.bl_idname), None)
        if interactive_op:
            interactive_op._dialog_success = False
            
        settings = context.scene.scale_interactive_settings
        self.target_dimension = convert_to_display_unit(self.measured_distance, settings) if self.measured_distance > 1e-4 else 1.0
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.scale_interactive_settings
        precision = int(settings.decimal_precision)
        unit_suffix = get_unit_suffix(settings)
        display_measured = convert_to_display_unit(self.measured_distance, settings)
        
        # --- ADDED: Check for rounding approximation ---
        rounded_display = round(display_measured, precision)
        high_precision_display = round(display_measured, precision + 2)
        prefix = "~ " if abs(rounded_display - high_precision_display) > 1e-5 else ""
        
        layout.label(text=f"Measured: {prefix}{display_measured:.{precision}f} {unit_suffix}")
        layout.prop(self, "target_dimension", text=f"Target ({unit_suffix})")

    def execute(self, context):
        settings = context.scene.scale_interactive_settings
        if self.measured_distance <= 1e-6 or self.target_dimension <= 1e-6:
            self.report({'ERROR'}, "Distances must be positive.")
            return self._cancel_and_return(context)

        target_meters = convert_from_display_unit(self.target_dimension, settings)
        scaling_factor = target_meters / self.measured_distance
        
        objects_to_scale = [context.scene.objects.get(name) for name in self.selected_object_names.split(",")]
        objects_to_scale = [obj for obj in objects_to_scale if obj]

        if not objects_to_scale:
            self.report({'ERROR'}, "No valid objects found for scaling.")
            return self._cancel_and_return(context)

        was_in_object_mode = context.mode == 'OBJECT'
        original_active = context.view_layer.objects.active
        original_selection = context.selected_objects[:]
        
        if not was_in_object_mode:
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects_to_scale:
            obj.select_set(True)
        if objects_to_scale:
            context.view_layer.objects.active = objects_to_scale[0]
        
        try:
            bpy.ops.transform.resize(value=(scaling_factor, scaling_factor, scaling_factor))
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True, properties=False)
        finally:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in original_selection:
                if obj and obj.name in context.scene.objects: obj.select_set(True)
            if original_active and original_active.name in context.scene.objects:
                context.view_layer.objects.active = original_active
            if not was_in_object_mode and context.view_layer.objects.active:
                try:
                    # Convert EDIT_MESH, EDIT_CURVE, etc. to just EDIT
                    return_mode = self.original_mode
                    if return_mode.startswith('EDIT_'):
                        return_mode = 'EDIT'
                    bpy.ops.object.mode_set(mode=return_mode)
                except RuntimeError:
                    pass
        
        self.report({'INFO'}, f"Scaled {len(objects_to_scale)} object(s).")
        
        # Find the main interactive operator and set its success flag
        interactive_op = next((o for o in context.window_manager.operators if o.bl_idname == OBJECT_OT_ScaleToDimensionInteractive.bl_idname), None)
        if interactive_op:
            interactive_op._dialog_success = True
            
        return {'FINISHED'}

    def cancel(self, context):
        return self._cancel_and_return(context)
        
    def _cancel_and_return(self, context):
        # Find the main interactive operator and ensure its success flag is False
        interactive_op = next((o for o in context.window_manager.operators if o.bl_idname == OBJECT_OT_ScaleToDimensionInteractive.bl_idname), None)
        if interactive_op:
            interactive_op._dialog_success = False
        self.report({'INFO'}, "Target dimension entry cancelled.")
        return {'CANCELLED'}

class VIEW3D_PT_ScaleToDimensionInteractivePanel(Panel):
    bl_label = "Measure and Scale"
    bl_idname = "VIEW3D_PT_scale_to_dimension_interactive"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.scale_interactive_settings
        col = layout.column(align=True)
        box = col.box()
        box.label(text="Display Units:")
        row = box.row(align=True)
        row.prop(settings, "system_unit", expand=True)
        if settings.system_unit == 'METRIC':
            row = box.row(align=True)
            row.prop(settings, "metric_unit", expand=True)
        row = box.row(align=True)
        row.prop(settings, "decimal_precision", text="Precision")
        col.separator()

        has_mesh_selection = any(o.type == 'MESH' for o in context.selected_objects)
        is_running = OBJECT_OT_ScaleToDimensionInteractive._draw_handle is not None

        op_row = layout.row()
        op_row.enabled = has_mesh_selection and not is_running
        op_row.operator(
            OBJECT_OT_ScaleToDimensionInteractive.bl_idname,
            text="Measure and Scale Selected",
            icon='ARROW_LEFTRIGHT'
        )

        if not has_mesh_selection:
            layout.label(text="Select a Mesh object.", icon='INFO')
        elif is_running:
            op_instance = next((o for o in context.window_manager.operators if o.bl_idname == OBJECT_OT_ScaleToDimensionInteractive.bl_idname), None)
            if op_instance:
                layout.label(text=op_instance.status_message, icon='INFO')
            else:
                layout.label(text="Measuring active...", icon='INFO')

classes = (
    ScaleInteractiveSettings,
    OBJECT_OT_ScaleToDimensionInteractive,
    OBJECT_OT_ScaleConfirmDialog,
    VIEW3D_PT_ScaleToDimensionInteractivePanel,
)

def register():
    if OBJECT_OT_ScaleToDimensionInteractive._draw_handle:
        try: bpy.types.SpaceView3D.draw_handler_remove(OBJECT_OT_ScaleToDimensionInteractive._draw_handle, 'WINDOW')
        except (ValueError, TypeError): pass
        OBJECT_OT_ScaleToDimensionInteractive._draw_handle = None
    
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.scale_interactive_settings = PointerProperty(type=ScaleInteractiveSettings)

def unregister():
    if OBJECT_OT_ScaleToDimensionInteractive._draw_handle:
        try: bpy.types.SpaceView3D.draw_handler_remove(OBJECT_OT_ScaleToDimensionInteractive._draw_handle, 'WINDOW')
        except (ValueError, TypeError): pass
        OBJECT_OT_ScaleToDimensionInteractive._draw_handle = None

    if hasattr(bpy.types.Scene, 'scale_interactive_settings'):
        try:
            del bpy.types.Scene.scale_interactive_settings
        except (AttributeError, RuntimeError):
            pass
    
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

if __name__ == "__main__":
    try:
        unregister()
    except Exception:
        pass
    register()