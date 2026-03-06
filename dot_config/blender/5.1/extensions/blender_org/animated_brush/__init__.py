import bpy
from bpy.props import EnumProperty, BoolProperty
import random

is_painting = False
modal_running = False
_modal_operator_instance = None


def cycle_frame(tex):
    iu = tex.image_user
    iu.frame_current = random.randint(1, iu.frame_duration)


def brush_is_sequence(context):
    """Detect if the active brush has a texture with an image sequence."""
    brush = None

    if context.mode == 'PAINT_TEXTURE':
        brush = context.tool_settings.image_paint.brush
    elif context.mode == 'SCULPT':
        brush = context.tool_settings.sculpt.brush
    elif context.mode == 'PAINT_VERTEX':
        brush = context.tool_settings.vertex_paint.brush

    if not brush:
        return False, None

    for tex in (brush.texture, brush.mask_texture):
        if not tex:
            continue
        img = tex.image
        if img and img.source == 'SEQUENCE':
            return True, tex

    return False, None


class BRUSH_OT_paint_modal(bpy.types.Operator):
    """Animated Brush Modal Operator"""
    bl_idname = "paint.animated_brush_modal"
    bl_label = "Animated Brush Modal"

    _timer = None

    def modal(self, context, event):
        global is_painting, modal_running

        prefs = context.preferences.addons[__package__].preferences

        # Stop if toggle is off
        if not prefs.enable_modal:
            self.cancel(context)
            return {'CANCELLED'}

        # Allow Texture Paint, Sculpt, and Vertex Paint
        if context.mode not in {'PAINT_TEXTURE', 'SCULPT', 'PAINT_VERTEX'}:
            self.cancel(context)
            return {'CANCELLED'}

        is_seq, tex = brush_is_sequence(context)
        if not is_seq:
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            is_painting = True
            if prefs.cycle_mode == 'PER_STROKE':
                cycle_frame(tex)

        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            is_painting = False

        if prefs.cycle_mode == 'CONTINUOUS' and is_painting:
            if event.type in {'MOUSEMOVE', 'TIMER'}:
                cycle_frame(tex)

        return {'PASS_THROUGH'}

    def execute(self, context):
        global modal_running, _modal_operator_instance
        if modal_running:
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        modal_running = True
        _modal_operator_instance = self
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        global modal_running, _modal_operator_instance
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        modal_running = False
        _modal_operator_instance = None


class AnimatedBrushPrefs(bpy.types.AddonPreferences):
    bl_idname = __package__

    cycle_mode: EnumProperty(
        name="Cycle Mode",
        description="How brush animation frames are advanced",
        items=[
            ('CONTINUOUS', "Continuous", "Advance frames continuously while painting"),
            ('PER_STROKE', "Per Stroke", "Advance frame once per stroke"),
        ],
        default='CONTINUOUS'
    )

    enable_modal: BoolProperty(
        name="Enable Animated Texture Brush",
        description="Toggle the animated texture brush modal operator",
        default=False,
        update=lambda self, context: toggle_modal(self, context)
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "cycle_mode")
        layout.prop(self, "enable_modal")


def toggle_modal(self, context):
    global modal_running, _modal_operator_instance
    if self.enable_modal:
        if not modal_running:
            try:
                bpy.ops.paint.animated_brush_modal()
            except Exception as e:
                print(f"Failed to start modal operator: {e}")
    else:
        if _modal_operator_instance:
            _modal_operator_instance.cancel(context)


class PAINT_PT_animated_brush_panel(bpy.types.Panel):
    bl_label = "Animated Texture Brush"
    bl_idname = "PAINT_PT_animated_brush_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    @classmethod
    def poll(cls, context):
        # Show in Texture Paint, Sculpt, and Vertex Paint modes
        return context.mode in {'PAINT_TEXTURE', 'SCULPT', 'PAINT_VERTEX'}

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences
        layout.prop(prefs, "enable_modal", toggle=True)
        layout.prop(prefs, "cycle_mode")


classes = (
    AnimatedBrushPrefs,
    BRUSH_OT_paint_modal,
    PAINT_PT_animated_brush_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
