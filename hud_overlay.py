# Bonsai - OpenBIM Blender Add-on
# HUD Overlay System for 4D Animation
# Copyright (C) 2024

import bpy
import gpu
import blf
from gpu_extras.batch import batch_for_shader
from datetime import datetime, timedelta  # noqa: F401  (used by Bonsai tool down the stack)
import json  # noqa: F401
from mathutils import Vector  # noqa: F401

# Global handler reference
_hud_draw_handler = None
_hud_enabled = False


class ScheduleHUD:
    """Sistema de HUD mejorado para mostrar información del cronograma"""

    def __init__(self):
        self.font_id = 0
        self.font_size = 16
        self.margin = 20
        self.line_height = 25
        # Valores por defecto (se sobrescriben con get_hud_settings)
        self.text_color = (1.0, 1.0, 1.0, 1.0)
        self.background_color = (0.0, 0.0, 0.0, 0.5)
        self.text_shadow_enabled = True
        self.text_shadow_offset = (1.0, -1.0)
        self.text_shadow_color = (0.0, 0.0, 0.0, 0.8)

    def get_schedule_data(self):
        """Extrae datos del cronograma actual"""
        try:
            import bonsai.tool as tool

            # Obtener propiedades (no usadas directamente, pero mantienen compatibilidad)
            _ = tool.Sequence.get_work_schedule_props()
            _ = tool.Sequence.get_animation_props()

            # Fechas de visualización
            viz_start = tool.Sequence.get_start_date()
            viz_finish = tool.Sequence.get_finish_date()

            if not (viz_start and viz_finish):
                return None

            # Frame actual y configuración
            scene = bpy.context.scene
            current_frame = scene.frame_current
            start_frame = scene.frame_start
            end_frame = scene.frame_end

            # Calcular fecha actual basada en frame
            if end_frame > start_frame:
                progress = (current_frame - start_frame) / (end_frame - start_frame)
                progress = max(0.0, min(1.0, progress))

                duration = viz_finish - viz_start
                current_date = viz_start + (duration * progress)
            else:
                current_date = viz_start

            # Calcular métricas
            total_days = (viz_finish - viz_start).days + 1
            elapsed_days = (current_date - viz_start).days + 1
            elapsed_days = max(1, min(total_days, elapsed_days))

            # Semana desde el inicio
            week_number = ((elapsed_days - 1) // 7) + 1

            # Progreso porcentual
            if total_days > 0:
                progress_pct = min(100, max(1, round((elapsed_days / total_days) * 100)))
            else:
                progress_pct = 100

            return {
                'current_date': current_date,
                'start_date': viz_start,
                'finish_date': viz_finish,
                'current_frame': current_frame,
                'total_days': total_days,
                'elapsed_days': elapsed_days,
                'week_number': week_number,
                'progress_pct': progress_pct,
                'day_of_week': current_date.strftime('%A'),
            }

        except Exception as e:
            print(f"Error getting schedule data: {e}")
            return None

    def get_hud_settings(self):
        """Obtiene configuración completa del HUD desde las propiedades"""
        try:
            import bonsai.tool as tool
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            return {
                'enabled': getattr(camera_props, 'enable_text_hud', False),
                'position': getattr(camera_props, 'hud_position', 'TOP_RIGHT'),
                'margin_h': getattr(camera_props, 'hud_margin_horizontal', 0.05),
                'margin_v': getattr(camera_props, 'hud_margin_vertical', 0.05),
                'spacing': getattr(camera_props, 'hud_text_spacing', 0.08),
                'scale': getattr(camera_props, 'hud_scale_factor', 1.0),
                'text_color': getattr(camera_props, 'hud_text_color', (1.0, 1.0, 1.0, 1.0)),
                'background_color': getattr(camera_props, 'hud_background_color', (0.0, 0.0, 0.0, 0.8)),
                'text_alignment': getattr(camera_props, 'hud_text_alignment', 'LEFT'),
                'padding_h': getattr(camera_props, 'hud_padding_horizontal', 10.0),
                'padding_v': getattr(camera_props, 'hud_padding_vertical', 8.0),
                'border_radius': getattr(camera_props, 'hud_border_radius', 5.0),
                'border_width': getattr(camera_props, 'hud_border_width', 0.0),
                'border_color': getattr(camera_props, 'hud_border_color', (1.0, 1.0, 1.0, 0.5)),
                'text_shadow_enabled': getattr(camera_props, 'hud_text_shadow_enabled', True),
                'text_shadow_offset_x': getattr(camera_props, 'hud_text_shadow_offset_x', 1.0),
                'text_shadow_offset_y': getattr(camera_props, 'hud_text_shadow_offset_y', -1.0),
                'text_shadow_color': getattr(camera_props, 'hud_text_shadow_color', (0.0, 0.0, 0.0, 0.8)),
                'background_shadow_enabled': getattr(camera_props, 'hud_background_shadow_enabled', False),
                'background_shadow_offset_x': getattr(camera_props, 'hud_background_shadow_offset_x', 3.0),
                'background_shadow_offset_y': getattr(camera_props, 'hud_background_shadow_offset_y', -3.0),
                'background_shadow_blur': getattr(camera_props, 'hud_background_shadow_blur', 5.0),
                'background_shadow_color': getattr(camera_props, 'hud_background_shadow_color', (0.0, 0.0, 0.0, 0.6)),
                'font_weight': getattr(camera_props, 'hud_font_weight', 'NORMAL'),
                'letter_spacing': getattr(camera_props, 'hud_letter_spacing', 0.0),
                'background_gradient_enabled': getattr(camera_props, 'hud_background_gradient_enabled', False),
                'background_gradient_color': getattr(camera_props, 'hud_background_gradient_color', (0.1, 0.1, 0.1, 0.9)),
                'gradient_direction': getattr(camera_props, 'hud_gradient_direction', 'VERTICAL'),
                # Flags de visibilidad
                'hud_show_date': getattr(camera_props, 'hud_show_date', True),
                'hud_show_week': getattr(camera_props, 'hud_show_week', True),
                'hud_show_day': getattr(camera_props, 'hud_show_day', True),
                'hud_show_progress': getattr(camera_props, 'hud_show_progress', True),
            }
        except Exception as e:
            print(f"Error getting HUD settings: {e}")
            return {
                'enabled': False,
                'position': 'TOP_RIGHT',
                'margin_h': 0.05,
                'margin_v': 0.05,
                'spacing': 0.08,
                'scale': 1.0,
                'text_color': (1.0, 1.0, 1.0, 1.0),
                'background_color': (0.0, 0.0, 0.0, 0.8),
                'text_alignment': 'LEFT',
                'padding_h': 10.0,
                'padding_v': 8.0,
                'border_radius': 5.0,
                'border_width': 0.0,
                'border_color': (1.0, 1.0, 1.0, 0.5),
                'text_shadow_enabled': True,
                'text_shadow_offset_x': 1.0,
                'text_shadow_offset_y': -1.0,
                'text_shadow_color': (0.0, 0.0, 0.0, 0.8),
                'background_shadow_enabled': False,
                'background_shadow_offset_x': 3.0,
                'background_shadow_offset_y': -3.0,
                'background_shadow_blur': 5.0,
                'background_shadow_color': (0.0, 0.0, 0.0, 0.6),
                'font_weight': 'NORMAL',
                'letter_spacing': 0.0,
                'background_gradient_enabled': False,
                'background_gradient_color': (0.1, 0.1, 0.1, 0.9),
                'gradient_direction': 'VERTICAL',
                'hud_show_date': True,
                'hud_show_week': True,
                'hud_show_day': True,
                'hud_show_progress': True,
            }

    def calculate_position(self, viewport_width, viewport_height, settings):
        """Calcula la posición del HUD en píxeles"""
        margin_h = int(viewport_width * settings['margin_h'])
        margin_v = int(viewport_height * settings['margin_v'])

        position = settings['position']

        if position == 'TOP_RIGHT':
            x = viewport_width - margin_h
            y = viewport_height - margin_v
            align_x = 'RIGHT'
            align_y = 'TOP'
        elif position == 'TOP_LEFT':
            x = margin_h
            y = viewport_height - margin_v
            align_x = 'LEFT'
            align_y = 'TOP'
        elif position == 'BOTTOM_RIGHT':
            x = viewport_width - margin_h
            y = margin_v
            align_x = 'RIGHT'
            align_y = 'BOTTOM'
        else:  # BOTTOM_LEFT
            x = margin_h
            y = margin_v
            align_x = 'LEFT'
            align_y = 'BOTTOM'

        return x, y, align_x, align_y

    def format_text_lines(self, data):
        """Formatea las líneas de texto del HUD"""
        if not data:
            return ["No Schedule Data"]

        lines = [
            f"{data['current_date'].strftime('%d %B %Y')}",
            f"Week {data['week_number']} - {data['day_of_week']}",
            f"Day {data['elapsed_days']} of {data['total_days']}",
            f"Progress: {data['progress_pct']}%",
        ]

        return lines

    def draw_background_with_effects(self, x, y, width, height, align_x, align_y, settings):
        """Dibuja fondo con efectos mejorados y coordenadas corregidas.
        `width` y `height` deben ser SOLO del bloque de texto (sin padding)."""
        padding_h = settings.get('padding_h', 10.0)
        padding_v = settings.get('padding_v', 8.0)

        # Ancho y alto finales incluyendo padding
        final_width = width + (padding_h * 2)
        final_height = height + (padding_v * 2)

        # Calcular posición del fondo según alineación
        if align_x == 'RIGHT':
            bg_x = x - final_width
        elif align_x == 'CENTER':
            bg_x = x - (final_width / 2)
        else:  # LEFT
            bg_x = x

        if align_y == 'TOP':
            bg_y = y - final_height
        else:  # BOTTOM
            bg_y = y

        # Dibujar sombra del fondo si está habilitada
        if settings.get('background_shadow_enabled', False):
            shadow_offset_x = settings.get('background_shadow_offset_x', 3.0)
            shadow_offset_y = settings.get('background_shadow_offset_y', -3.0)
            shadow_color = settings.get('background_shadow_color', (0.0, 0.0, 0.0, 0.6))

            shadow_vertices = [
                (bg_x + shadow_offset_x, bg_y + shadow_offset_y),
                (bg_x + final_width + shadow_offset_x, bg_y + shadow_offset_y),
                (bg_x + final_width + shadow_offset_x, bg_y + final_height + shadow_offset_y),
                (bg_x + shadow_offset_x, bg_y + final_height + shadow_offset_y),
            ]

            shadow_indices = [(0, 1, 2), (2, 3, 0)]

            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'TRIS', {"pos": shadow_vertices}, indices=shadow_indices)

            gpu.state.blend_set('ALPHA')
            shader.bind()
            shader.uniform_float("color", shadow_color)
            batch.draw(shader)

        # Crear vértices del fondo principal
        vertices = [
            (bg_x, bg_y),
            (bg_x + final_width, bg_y),
            (bg_x + final_width, bg_y + final_height),
            (bg_x, bg_y + final_height),
        ]

        indices = [(0, 1, 2), (2, 3, 0)]

        # Dibujar fondo (gradiente o color sólido)
        if settings.get('background_gradient_enabled', False):
            self.draw_gradient_background(vertices, indices, settings)
        else:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)

            gpu.state.blend_set('ALPHA')
            shader.bind()
            shader.uniform_float("color", settings.get('background_color', (0.0, 0.0, 0.0, 0.8)))
            batch.draw(shader)

        # Dibujar borde si está habilitado
        border_width = settings.get('border_width', 0.0)
        if border_width > 0:
            self.draw_border(
                bg_x, bg_y, final_width, final_height, border_width,
                settings.get('border_color', (1.0, 1.0, 1.0, 0.5)),
            )

        gpu.state.blend_set('NONE')

    def draw_gradient_background(self, vertices, indices, settings):
        """Dibuja un fondo con gradiente (simplificado)"""
        try:
            color1 = settings.get('background_color', (0.0, 0.0, 0.0, 0.8))
            color2 = settings.get('background_gradient_color', (0.1, 0.1, 0.1, 0.9))

            # Para simplificar, usar color promedio
            avg_color = tuple((c1 + c2) / 2 for c1, c2 in zip(color1, color2))

            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)

            gpu.state.blend_set('ALPHA')
            shader.bind()
            shader.uniform_float("color", avg_color)
            batch.draw(shader)
        except Exception as e:
            print(f"Error drawing gradient: {e}")
            # Fallback a color sólido
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)
            gpu.state.blend_set('ALPHA')
            shader.bind()
            shader.uniform_float("color", settings.get('background_color', (0.0, 0.0, 0.0, 0.8)))
            batch.draw(shader)

    def draw_border(self, x, y, width, height, border_width, border_color):
        """Dibuja un borde alrededor del rectángulo"""
        try:
            # Líneas del borde
            border_lines = [
                # Top
                [(x, y + height), (x + width, y + height)],
                # Bottom
                [(x, y), (x + width, y)],
                # Left
                [(x, y), (x, y + height)],
                # Right
                [(x + width, y), (x + width, y + height)],
            ]

            gpu.state.blend_set('ALPHA')
            gpu.state.line_width_set(border_width)

            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            for line in border_lines:
                batch = batch_for_shader(shader, 'LINES', {"pos": line})
                shader.bind()
                shader.uniform_float("color", border_color)
                batch.draw(shader)

            gpu.state.line_width_set(1.0)  # Reset line width
        except Exception as e:
            print(f"Error drawing border: {e}")

    def draw_text_with_shadow(self, text, x, y, settings, align_x='LEFT'):
        """Dibuja texto con sombra y alineación mejorada usando baseline correcto"""
        # Configurar fuente
        font_size = int(settings.get('scale', 1.0) * 16)
        blf.size(self.font_id, font_size)

        # Calcular ancho del texto para alineación
        text_width, text_height = blf.dimensions(self.font_id, text)

        # Ajustar posición X según alineación
        text_alignment = settings.get('text_alignment', 'LEFT')
        if text_alignment == 'RIGHT' or align_x == 'RIGHT':
            text_x = x - text_width
        elif text_alignment == 'CENTER' or align_x == 'CENTER':
            text_x = x - (text_width / 2)
        else:  # LEFT
            text_x = x

        # Y viene como baseline
        text_y = y

        # Dibujar sombra del texto si está habilitada
        if settings.get('text_shadow_enabled', True):
            shadow_offset_x = settings.get('text_shadow_offset_x', 1.0)
            shadow_offset_y = settings.get('text_shadow_offset_y', -1.0)
            shadow_color = settings.get('text_shadow_color', (0.0, 0.0, 0.0, 0.8))

            blf.position(self.font_id, text_x + shadow_offset_x, text_y + shadow_offset_y, 0)
            blf.color(self.font_id, *shadow_color)
            blf.draw(self.font_id, text)

        # Dibujar texto principal
        text_color = settings.get('text_color', (1.0, 1.0, 1.0, 1.0))
        blf.position(self.font_id, text_x, text_y, 0)
        blf.color(self.font_id, *text_color)
        blf.draw(self.font_id, text)

        return text_width, text_height

    def draw(self):
        """Función principal de dibujo del HUD con diagnóstico mejorado"""
        try:
            # Evitar depender de bpy.context.area directamente
            if not hasattr(bpy.context, 'region') or not bpy.context.region:
                # No hay región válida para dibujar
                return

            if not hasattr(bpy.context, 'space_data') or not bpy.context.space_data:
                return

            if bpy.context.space_data.type != 'VIEW_3D':
                return

            settings = self.get_hud_settings()
            if not settings.get('enabled', False):
                return

            # Obtener datos del cronograma (puede ser None si no hay animación)
            data = self.get_schedule_data()

            # Obtener dimensiones del viewport
            region = bpy.context.region
            viewport_width = getattr(region, 'width', 0) or 0
            viewport_height = getattr(region, 'height', 0) or 0
            if viewport_width <= 0 or viewport_height <= 0:
                return

            x, y, align_x, align_y = self.calculate_position(viewport_width, viewport_height, settings)

            # Determinar qué líneas mostrar
            if not data:
                lines_to_draw = ["No active schedule data.", "Please create an animation."]
            else:
                lines_to_draw = []
                if settings.get('hud_show_date', True):
                    lines_to_draw.append(f"{data['current_date'].strftime('%d %B %Y')}")
                if settings.get('hud_show_week', True):
                    lines_to_draw.append(f"Week {data['week_number']} - {data['day_of_week']}")
                if settings.get('hud_show_day', True):
                    lines_to_draw.append(f"Day {data['elapsed_days']} of {data['total_days']}")
                if settings.get('hud_show_progress', True):
                    lines_to_draw.append(f"Progress: {data['progress_pct']}%")

            if not lines_to_draw:
                return

            # Configurar fuente
            font_size = int(settings.get('scale', 1.0) * 16)
            blf.size(self.font_id, font_size)

            # Calcular dimensiones del bloque de texto
            line_dims = [blf.dimensions(self.font_id, line) for line in lines_to_draw]
            line_heights = [h for (_, h) in line_dims]
            line_widths = [w for (w, _) in line_dims]
            max_width = max(line_widths) if line_widths else 0.0
            line_spacing = settings.get('spacing', 0.02) * viewport_height
            total_text_height = sum(line_heights) + max(0, len(lines_to_draw) - 1) * line_spacing

            # Dibujar fondo (pasar SOLO el alto del texto; la función agrega padding)
            self.draw_background_with_effects(x, y, max_width, total_text_height, align_x, align_y, settings)

            # Calcular posición inicial Y del primer texto
            padding_v = settings.get('padding_v', 8.0)
            if align_y == 'TOP':
                # Empezar desde la parte superior del área de texto (después del padding superior)
                current_y = y - padding_v - line_heights[0]
            else:  # BOTTOM
                # Empezar desde la parte inferior del bloque y subir
                current_y = y + padding_v + total_text_height - line_heights[0]

            padding_h = settings.get('padding_h', 10.0)
            text_alignment = settings.get('text_alignment', 'LEFT')

            # Dibujar cada línea de texto con soporte para align_x == 'CENTER'
            for i, line in enumerate(lines_to_draw):
                # Calcular posición X según la alineación del bloque y del texto
                if align_x == 'RIGHT':
                    # Borde derecho del área de texto
                    text_x = x - padding_h
                    self.draw_text_with_shadow(line, text_x, current_y, settings, 'RIGHT')
                elif align_x == 'CENTER':
                    # Área de texto centrada: [x - max_width/2, x + max_width/2]
                    if text_alignment == 'LEFT':
                        text_x = x - (max_width / 2)
                        self.draw_text_with_shadow(line, text_x, current_y, settings, 'LEFT')
                    elif text_alignment == 'RIGHT':
                        text_x = x + (max_width / 2)
                        self.draw_text_with_shadow(line, text_x, current_y, settings, 'RIGHT')
                    else:  # CENTER
                        text_x = x
                        self.draw_text_with_shadow(line, text_x, current_y, settings, 'CENTER')
                else:  # LEFT
                    # Borde izquierdo del área de texto
                    text_x = x + padding_h
                    self.draw_text_with_shadow(line, text_x, current_y, settings, 'LEFT')

                # Mover Y para la siguiente línea
                if i < len(lines_to_draw) - 1:
                    # bajar por altura de la siguiente línea + espaciado
                    current_y -= (line_spacing + line_heights[i + 1])

        except Exception as e:
            print(f"HUD draw error: {e}")
            import traceback
            traceback.print_exc()


def draw_hud_callback():
    """Callback que se ejecuta cada frame para dibujar el HUD"""
    try:
        schedule_hud.draw()
    except Exception as e:
        print(f"🔴 HUD callback error: {e}")
        import traceback
        traceback.print_exc()


# Global instance of the HUD
schedule_hud = ScheduleHUD()


def register_hud_handler():
    """Registra el handler de dibujo del HUD"""
    global _hud_draw_handler, _hud_enabled

    if _hud_draw_handler is not None:
        unregister_hud_handler()

    try:
        _hud_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_hud_callback, (), 'WINDOW', 'POST_PIXEL'
        )
        _hud_enabled = True
        print("✅ HUD handler registered successfully")

        # Forzar redibujado inmediato
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    except Exception as e:
        print(f"🔴 Error registering HUD handler: {e}")
        _hud_enabled = False


def unregister_hud_handler():
    """Desregistra el handler de dibujo del HUD"""
    global _hud_draw_handler, _hud_enabled

    if _hud_draw_handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_hud_draw_handler, 'WINDOW')
            print("✅ HUD handler unregistered successfully")
        except Exception as e:
            print(f"🔴 Error removing HUD handler: {e}")
        _hud_draw_handler = None

    _hud_enabled = False


def is_hud_enabled():
    """Verifica si el HUD está activo"""
    return _hud_enabled


def refresh_hud():
    """Fuerza el refresco del viewport para actualizar el HUD"""
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
        print("🔄 HUD refresh requested")
    except Exception as e:
        print(f"🔴 HUD refresh error: {e}")


# 🔧 FUNCIÓN DE DIAGNÓSTICO ADICIONAL
def debug_hud_state():
    """Función de diagnóstico para depurar el estado del HUD"""
    print("\n🔍 === HUD DEBUG STATE ===")
    print(f"Handler enabled: {_hud_enabled}")
    print(f"Handler object: {_hud_draw_handler}")

    try:
        import bonsai.tool as tool
        anim_props = tool.Sequence.get_animation_props()
        camera_props = anim_props.camera_orbit
        hud_enabled = getattr(camera_props, 'enable_text_hud', False)
        print(f"Property enable_text_hud: {hud_enabled}")

        # Verificar datos de cronograma
        data = schedule_hud.get_schedule_data()
        print(f"Schedule data available: {data is not None}")
        if data:
            print(f"  Current date: {data.get('current_date')}")
            print(f"  Frame: {data.get('current_frame')}")

    except Exception as e:
        print(f"Error in debug: {e}")

    print("=== END DEBUG ===\n")
