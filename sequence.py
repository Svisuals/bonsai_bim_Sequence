# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>, 2022 Yassine Oualid <yassine@sigmadimensions.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations
import os
import re
import bpy
from bonsai.bim.module.sequence import data as _seq_data
import json
import base64
import ifcopenshell.api.sequence
import pystache
import mathutils
import webbrowser
import isodate
import ifcopenshell
import ifcopenshell.api.group
import ifcopenshell.ifcopenshell_wrapper as W
import ifcopenshell.util.date
import ifcopenshell.util.selector
import ifcopenshell.util.sequence
import bonsai.core.tool
import bonsai.tool as tool
import bonsai.bim.helper
from dateutil import parser
from datetime import datetime
from datetime import time as datetime_time
from typing import Optional, Any, Union, Literal, TYPE_CHECKING
from typing import Union
from collections.abc import Iterable
from mathutils import Color

if TYPE_CHECKING:
    from bonsai.bim.prop import Attribute
    from bonsai.bim.module.sequence.prop import (
        BIMAnimationProperties,
        BIMStatusProperties,
        BIMTaskTreeProperties,
        BIMWorkCalendarProperties,
        BIMWorkPlanProperties,
        BIMWorkScheduleProperties,
    )


class Sequence(bonsai.core.tool.Sequence):


    # === INICIO DE CÓDIGO AÑADIDO ===
    @classmethod
    def apply_selection_from_checkboxes(cls):
        """
        Selecciona en el viewport los objetos 3D de todas las tareas marcadas con el checkbox.
        Deselecciona todo lo demás.
        """
        try:
            tprops = cls.get_task_tree_props()
            if not tprops:
                return

            # 1. Obtener todas las tareas que están marcadas con el checkbox
            selected_tasks_pg = [task_pg for task_pg in tprops.tasks if getattr(task_pg, 'is_selected', False)]

            # 2. Deseleccionar todo en la escena
            bpy.ops.object.select_all(action='DESELECT')

            # 3. Si no hay tareas marcadas, terminar
            if not selected_tasks_pg:
                return

            # 4. Recopilar todos los objetos a seleccionar
            objects_to_select = []
            for task_pg in selected_tasks_pg:
                task_ifc = tool.Ifc.get().by_id(task_pg.ifc_definition_id)
                if not task_ifc:
                    continue
                
                outputs = cls.get_task_outputs(task_ifc)
                for product in outputs:
                    obj = tool.Ifc.get_object(product)
                    if obj:
                        objects_to_select.append(obj)

            # 5. Seleccionar todos los objetos recopilados
            if objects_to_select:
                for obj in objects_to_select:
                    obj.select_set(True)
                # Hacer el primer objeto de la lista el activo
                bpy.context.view_layer.objects.active = objects_to_select[0]

        except Exception as e:
            print(f"Error applying selection from checkboxes: {e}")
    # === FIN DE CÓDIGO AÑADIDO ===




    @classmethod
    def add_text_animation_handler(cls, settings):
        """Crea múltiples objetos de texto animados con soporte para HUD.
        Esta es una implementación de respaldo: intenta llamar a la versión existente si está disponible.
        """
        created_texts = []
        # ... aquí iría el código existente para crear textos ...
        try:
            base_impl = getattr(super(), "add_text_animation_handler", None)
            if callable(base_impl):
                created_texts = base_impl(settings)
        except Exception as e:
            print(f"Fallback add_text_animation_handler error: {e}")

        
        try:
            cls._register_multi_text_handler(settings)
        except Exception as e:
            print(f"Error registering multi text handler: {e}")

        # --- CONFIGURACIÓN AUTOMÁTICA DEL HUD GPU ---
        try:
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # Auto-habilitar HUD GPU si hay cronograma válido
            if settings and settings.get("start") and settings.get("finish"):
                print("🎯 Auto-enabling GPU HUD for 4D animation...")
                # Activar HUD GPU automáticamente
                bpy.ops.bim.enable_schedule_hud()
                print("✅ GPU HUD auto-configured successfully")

        except Exception as e:
            print(f"⚠️ Auto-setup of GPU HUD failed: {e}")
        return created_texts


    @staticmethod
    def _apply_bezier_smoothing(fcurve, smoothness_factor):
        """Ajusta las manijas de una F-Curve para controlar la suavidad."""
        if len(fcurve.keyframe_points) < 2:
            return

        for i, kf in enumerate(fcurve.keyframe_points):
            kf.handle_left_type = 'ALIGNED'
            kf.handle_right_type = 'ALIGNED'

            # Calcular delta de tiempo con los vecinos
            delta_prev = kf.co.x - fcurve.keyframe_points[max(0, i - 1)].co.x
            delta_next = fcurve.keyframe_points[min(len(fcurve.keyframe_points) - 1, i + 1)].co.x - kf.co.x

            # Ajustar la posición X de las manijas basada en el factor de suavidad
            # Un factor de ~0.333 es un buen punto de partida para Bezier estándar
            handle_strength = max(delta_prev, delta_next) * smoothness_factor
            kf.handle_left.x = kf.co.x - handle_strength
            kf.handle_right.x = kf.co.x + handle_strength

            # Mantener las manijas Y alineadas para evitar sobrepasar la curva
            kf.handle_left.y = kf.co.y
            kf.handle_right.y = kf.co.y

        fcurve.update()
    @classmethod
    def load_profile_group_data(cls, group_name):
        """Carga datos de un grupo de perfiles específico"""
        import bpy, json
        scene = bpy.context.scene
        raw = scene.get("BIM_AppearanceProfileSets", "{}")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            return data.get(group_name, {})
        except Exception:
            return {}

    @classmethod
    def get_all_profile_groups(cls):
        """Obtiene todos los grupos de perfiles disponibles"""
        import bpy
        return UnifiedProfileManager.get_all_groups(bpy.context)

    @classmethod
    def get_custom_profile_groups(cls):
        """Obtiene solo los grupos personalizados (sin DEFAULT)"""
        import bpy
        return UnifiedProfileManager.get_user_created_groups(bpy.context)
    @classmethod
    def update_task_ICOM(cls, task: Union[ifcopenshell.entity_instance, None]) -> None:
        """Refresca los datos ICOM (Outputs, Inputs, Resources) del panel para la tarea activa.
        Si no hay tarea, limpia las listas para evitar restos de la tarea anterior."""
        props = cls.get_work_schedule_props()
        if task:
            # Outputs
            outputs = cls.get_task_outputs(task) or []
            cls.load_task_outputs(outputs)
            # Inputs
            inputs = cls.get_task_inputs(task) or []
            cls.load_task_inputs(inputs)
            # Resources
            cls.load_task_resources(task)
        else:
            props.task_outputs.clear()
            props.task_inputs.clear()
            props.task_resources.clear()


    @classmethod
    def _get_active_schedule_bbox(cls):
        """Return (center (Vector), dims (Vector), obj_list) for active WorkSchedule products.
        Fallbacks to visible mesh objects if empty."""
        import bpy, mathutils
        ws = cls.get_active_work_schedule()
        objs = []
        if ws:
            try:
                products = cls.get_work_schedule_products(ws)  # IFC entities
                want_ids = {p.id() for p in products if hasattr(p, "id")}
                for obj in bpy.data.objects:
                    try:
                        if not hasattr(obj, "type") or obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
                            continue
                        if (ifc_id := tool.Blender.get_ifc_definition_id(obj)) and ifc_id in want_ids:
                            objs.append(obj)
                    except Exception:
                        continue
            except Exception:
                pass

        if not objs:
            # Fallback: all visible mesh objs
            objs = [o for o in bpy.data.objects if getattr(o, "type", "") == "MESH" and not o.hide_get()]

        if not objs:
            c = mathutils.Vector((0.0, 0.0, 0.0))
            d = mathutils.Vector((10.0, 10.0, 5.0))
            return c, d, []

        mins = mathutils.Vector(( 1e18,  1e18,  1e18))
        maxs = mathutils.Vector((-1e18, -1e18, -1e18))
        for o in objs:
            try:
                for corner in o.bound_box:
                    wc = o.matrix_world @ mathutils.Vector(corner)
                    mins.x = min(mins.x, wc.x); mins.y = min(mins.y, wc.y); mins.z = min(mins.z, wc.z)
                    maxs.x = max(maxs.x, wc.x); maxs.y = max(maxs.y, wc.y); maxs.z = max(maxs.z, wc.z)
            except Exception:
                continue
        center = (mins + maxs) * 0.5
        dims = (maxs - mins)
        return center, dims, objs

    @classmethod
    def _get_or_create_target(cls, center, name="4D_OrbitTarget"):


        name = name or "4D_OrbitTarget"
        obj = bpy.data.objects.get(name)
        if obj is None:
            obj = bpy.data.objects.new(name, None)
            obj.empty_display_type = 'PLAIN_AXES'
            try:
                bpy.context.collection.objects.link(obj)
            except Exception:
                bpy.context.scene.collection.objects.link(obj)
        obj.location = center
        return obj

    @classmethod
    def add_animation_camera(cls):
        """Create a camera using Animation Settings (Camera/Orbit) and optionally animate it."""
        import bpy, math, mathutils
        from mathutils import Vector

        # Props - CORREGIDO: usar la nueva estructura
        anim = cls.get_animation_props()
        camera_props = anim.camera_orbit  # NUEVO: acceso a propiedades de cámara
        ws_props = cls.get_work_schedule_props()

        print("🎥 Creating 4D Animation Camera...")

        # --- LÍNEA AÑADIDA ---
        # CORRECCIÓN: Obtener las dimensiones y el centro de la escena ANTES de usarlos.
        center, dims, _ = cls._get_active_schedule_bbox()
        # ---------------------

        # Camera data - CORREGIDO
        cam_data = bpy.data.cameras.new("4D_Animation_Camera")
        cam_data.lens = camera_props.camera_focal_mm
        cam_data.clip_start = max(0.0001, camera_props.camera_clip_start)

        # CORREGIDO: Escalar clip_end con el tamaño de la escena
        clip_end = camera_props.camera_clip_end
        auto_scale = max(dims.x, dims.y, dims.z) * 5.0  # Factor más conservador
        cam_data.clip_end = max(clip_end, auto_scale)

        print(f"📷 Camera settings: focal={{cam_data.lens}}mm, clip={{cam_data.clip_start}}-{{cam_data.clip_end}}")

        cam_obj = bpy.data.objects.new("4D_Animation_Camera", cam_data)
        try:
            bpy.context.collection.objects.link(cam_obj)
        except Exception:
            bpy.context.scene.collection.objects.link(cam_obj)

        # CORRECCIÓN: Nombres únicos para los objetos auxiliares
        target_name = f"4D_OrbitTarget_for_{{cam_obj.name}}"
        # Target (auto u objeto)
        if camera_props.look_at_mode == "OBJECT" and camera_props.look_at_object:
            target = camera_props.look_at_object
            print(f"📍 Using custom target: {{target.name}}")
        else:
            target = cls._get_or_create_target(center, target_name)
            print(f"📍 Created/using auto target '{{target_name}}' at: {{center}}")

        # CORREGIDO: Compute radius & start angle
        if camera_props.orbit_radius_mode == "AUTO":
            # MEJORADO: Cálculo más inteligente del radio
            base = max(dims.x, dims.y)
            if base > 0:
                r = base * 1.5  # Factor más generoso
            else:
                r = 15.0  # Fallback más grande
            print(f"📐 Auto radius calculated: {{r:.2f}}m (from bbox: {{dims}})")
        else:
            r = max(0.01, camera_props.orbit_radius)
            print(f"📐 Manual radius: {{r:.2f}}m")

        z = center.z + camera_props.orbit_height
        angle0 = math.radians(camera_props.orbit_start_angle_deg)
        sign = -1.0 if camera_props.orbit_direction == "CW" else 1.0

        # CORREGIDO: Initial placement
        initial_x = center.x + r * math.cos(angle0)
        initial_y = center.y + r * math.sin(angle0)
        cam_obj.location = Vector((initial_x, initial_y, z))
        print(f"📍 Initial camera position: ({{initial_x:.2f}}, {{initial_y:.2f}}, {{z:.2f}})")

        # CORREGIDO: Always track target
        tcon = cam_obj.constraints.new(type='TRACK_TO')
        tcon.target = target
        tcon.track_axis = 'TRACK_NEGATIVE_Z'
        tcon.up_axis = 'UP_Y'
        print(f"🎯 Tracking target: {{target.name}}")

        # VERIFICAR: Orbit animation
        mode = camera_props.orbit_mode
        if mode == "NONE":
            print("🚫 Static camera only")
            bpy.context.scene.camera = cam_obj
            return cam_obj

        # CORREGIDO: Determine timeline
        try:
            settings = cls.get_animation_settings()
            if settings:
                total_frames_4d = int(settings["total_frames"])
                start_frame = int(settings["start_frame"])
            else:
                raise Exception("No animation settings")
        except Exception as e:
            print(f"⚠️ Using fallback timeline: {{e}}")
            total_frames_4d = 250
            start_frame = 1

        # CORREGIDO: Timeline calculation
        if camera_props.orbit_use_4d_duration:
            end_frame = start_frame + max(1, total_frames_4d - 1)
        else:
            end_frame = start_frame + int(max(1, camera_props.orbit_duration_frames))

        dur = max(1, end_frame - start_frame)
        print(f"⏱️ Animation timeline: frames {{start_frame}} to {{end_frame}} (duration: {{dur}})")

        # CORREGIDO: Orbit animation implementation
        if camera_props.orbit_path_method == "FOLLOW_PATH":
            print("🛤️ Creating Follow Path animation...")
            cls._create_follow_path_orbit(cam_obj, center, r, z, start_frame, end_frame, sign, mode)
        else:
            print("🔑 Creating Keyframe animation...")
            cls._create_keyframe_orbit(cam_obj, center, r, z, angle0, start_frame, end_frame, sign, mode)

        bpy.context.scene.camera = cam_obj
        print(f"✅ 4D Camera created successfully: {{cam_obj.name}}")
        return cam_obj
    @classmethod
    def update_animation_camera(cls, cam_obj):
        """
        Actualiza una cámara 4D existente. Limpia sus datos viejos y aplica
        la configuración actual de la UI.
        """
        import bpy, math, mathutils
        from mathutils import Vector

        # 1. Limpiar completamente la configuración anterior de la cámara
        if cam_obj.animation_data:
            cam_obj.animation_data_clear()

        for c in list(cam_obj.constraints):
            cam_obj.constraints.remove(c)

        # Limpiar la ruta y el target de órbita si existen (nombres únicos por cámara)
        path_name = f"4D_OrbitPath_for_{cam_obj.name}"
        path_obj = bpy.data.objects.get(path_name)
        if path_obj:
            bpy.data.objects.remove(path_obj, do_unlink=True)
        target_name = f"4D_OrbitTarget_for_{cam_obj.name}"
        tgt_obj = bpy.data.objects.get(target_name)
        if tgt_obj:
            bpy.data.objects.remove(tgt_obj, do_unlink=True)

        print(f"⚙️ Updating existing camera '{cam_obj.name}'...")

        # 2. Re-aplicar toda la configuración, usando la lógica de add_animation_camera
        anim = cls.get_animation_props()
        camera_props = anim.camera_orbit

        # Recalcular objetivo y dimensiones
        center, dims, _ = cls._get_active_schedule_bbox()
        target_name = f"4D_OrbitTarget_for_{cam_obj.name}"

        if camera_props.look_at_mode == "OBJECT" and camera_props.look_at_object:
            target = camera_props.look_at_object
        else:
            target = cls._get_or_create_target(center, target_name)

        # Reconfigurar datos de la cámara (lente, clipping)
        cam_data = cam_obj.data
        cam_data.lens = camera_props.camera_focal_mm
        cam_data.clip_start = camera_props.camera_clip_start
        cam_data.clip_end = max(camera_props.camera_clip_end, max(dims.x, dims.y, dims.z) * 5.0)

        # Recalcular posición
        if camera_props.orbit_radius_mode == "AUTO":
            r = max(dims.x, dims.y) * 1.5 if max(dims.x, dims.y) > 0 else 15.0
        else:
            r = max(0.01, camera_props.orbit_radius)

        z = center.z + camera_props.orbit_height
        angle0 = math.radians(camera_props.orbit_start_angle_deg)
        cam_obj.location = Vector((center.x + r * math.cos(angle0), center.y + r * math.sin(angle0), z))

        # Re-crear restricción de seguimiento
        tcon = cam_obj.constraints.new(type='TRACK_TO')
        tcon.target = target
        tcon.track_axis = 'TRACK_NEGATIVE_Z'
        tcon.up_axis = 'UP_Y'

        # Re-crear animación de órbita si está configurada
        mode = camera_props.orbit_mode
        if mode != "NONE":
            settings = cls.get_animation_settings()
            start_frame = settings["start_frame"]

            if camera_props.orbit_use_4d_duration:
                end_frame = start_frame + settings["total_frames"] -1
            else:
                end_frame = start_frame + int(camera_props.orbit_duration_frames)

            sign = -1.0 if camera_props.orbit_direction == "CW" else 1.0

            if camera_props.orbit_path_method == "FOLLOW_PATH":
                cls._create_follow_path_orbit(cam_obj, center, r, z, start_frame, end_frame, sign, mode)
            else:
                cls._create_keyframe_orbit(cam_obj, center, r, z, angle0, start_frame, end_frame, sign, mode)

        bpy.context.scene.camera = cam_obj
        print(f"✅ Camera '{cam_obj.name}' updated successfully.")
        return cam_obj
    # [[----- INICIO DEL CÓDIGO A AÑADIR -----]]
    # [[----- INICIO DEL CÓDIGO A AÑADIR -----]]
    @classmethod
    def clear_camera_animation(cls, cam_obj):
        """
        Limpia de forma robusta la animación y las restricciones de una cámara,
        incluyendo su trayectoria y objetivo asociados.
        """
        import bpy
        if not cam_obj:
            return

        try:
            # 1. Limpiar datos de animación (keyframes)
            if getattr(cam_obj, "animation_data", None):
                cam_obj.animation_data_clear()

            # 2. Limpiar todas las restricciones (constraints)
            for c in list(getattr(cam_obj, "constraints", [])):
                try:
                    cam_obj.constraints.remove(c)
                except Exception:
                    pass

            # 3. Limpiar objetos auxiliares (trayectoria y objetivo)
            path_name = f"4D_OrbitPath_for_{cam_obj.name}"
            path_obj = bpy.data.objects.get(path_name)
            if path_obj:
                bpy.data.objects.remove(path_obj, do_unlink=True)

            target_name = f"4D_OrbitTarget_for_{cam_obj.name}"
            tgt_obj = bpy.data.objects.get(target_name)
            if tgt_obj:
                bpy.data.objects.remove(tgt_obj, do_unlink=True)

            print(f"✅ Animation cleared for camera '{cam_obj.name}'")
        except Exception as e:
            print(f"⚠️ Error clearing camera animation: {e}")

    @classmethod
    def _create_follow_path_orbit(cls, cam_obj, center, radius, z, start_frame, end_frame, sign, mode):
        import bpy, math, mathutils
        anim = cls.get_animation_props()
        camera_props = anim.camera_orbit
        path_object = None

        if camera_props.orbit_path_shape == 'CUSTOM' and camera_props.custom_orbit_path:
            path_object = camera_props.custom_orbit_path
            path_object.hide_viewport = camera_props.hide_orbit_path
            path_object.hide_render = camera_props.hide_orbit_path
            print(f"🛤️ Using custom path: '{path_object.name}'")
        else:
            path_name = f"4D_OrbitPath_for_{cam_obj.name}"
            curve = bpy.data.curves.new(path_name, type='CURVE')
            curve.dimensions = '3D'
            curve.resolution_u = 64
            path_object = bpy.data.objects.new(path_name, curve)
            path_object.hide_viewport = camera_props.hide_orbit_path
            path_object.hide_render = camera_props.hide_orbit_path
            try:
                bpy.context.collection.objects.link(path_object)
            except Exception:
                bpy.context.scene.collection.objects.link(path_object)

            spline = curve.splines.new('BEZIER')
            num_points = 12
            spline.bezier_points.add(num_points - 1)
            for i in range(num_points):
                angle = (2 * math.pi * i) / num_points
                bp = spline.bezier_points[i]
                bp.co = mathutils.Vector((center.x + radius * math.cos(angle), center.y + radius * math.sin(angle), z))
                bp.handle_left_type = bp.handle_right_type = 'AUTO'
            spline.use_cyclic_u = True
            print(f"🛤️ Generated circular path: '{path_object.name}'")

        fcon = cam_obj.constraints.new(type='FOLLOW_PATH')
        fcon.target = path_object
        fcon.use_curve_follow = True
        fcon.use_fixed_location = True

        def key_offset(offset, frame):
            fcon.offset_factor = offset
            fcon.keyframe_insert("offset_factor", frame=frame)

        s0, s1 = (0.0, 1.0) if sign > 0 else (1.0, 0.0)

        if mode == "CIRCLE_360":
            key_offset(s0, start_frame)
            key_offset(s1, end_frame)
        elif mode == "PINGPONG":
            mid = start_frame + (end_frame - start_frame) // 2
            key_offset(s0, start_frame)
            key_offset(s0 + (s1 - s0) * 0.5, mid)
            key_offset(s0, end_frame)

        if cam_obj.animation_data and cam_obj.animation_data.action:
            for fcurve in cam_obj.animation_data.action.fcurves:
                if "offset_factor" in fcurve.data_path:
                    for kf in fcurve.keyframe_points:
                        kf.interpolation = camera_props.interpolation_mode
                    if camera_props.interpolation_mode == 'BEZIER':
                        cls._apply_bezier_smoothing(fcurve, camera_props.bezier_smoothness_factor)

        print(f"✅ Follow Path orbit created: {mode} from {start_frame} to {end_frame} with {camera_props.interpolation_mode} interpolation")

    @classmethod
    def _create_keyframe_orbit(cls, cam_obj, center, radius, z, angle0, start_frame, end_frame, sign, mode):
        import math, mathutils
        anim = cls.get_animation_props()
        camera_props = anim.camera_orbit

        def pt(theta):
            x = center.x + radius * math.cos(theta)
            y = center.y + radius * math.sin(theta)
            return mathutils.Vector((x, y, z))

        def key_loc(obj, loc, frame):
            obj.location = loc
            obj.keyframe_insert("location", frame=frame)

        if mode == "CIRCLE_360":
            key_loc(cam_obj, pt(angle0), start_frame)
            key_loc(cam_obj, pt(angle0 + sign * 2 * math.pi), end_frame)
        elif mode == "PINGPONG":
            mid = start_frame + (end_frame - start_frame) // 2
            key_loc(cam_obj, pt(angle0), start_frame)
            key_loc(cam_obj, pt(angle0 + sign * math.pi), mid)
            key_loc(cam_obj, pt(angle0), end_frame)

        if cam_obj.animation_data and cam_obj.animation_data.action:
            for fcurve in cam_obj.animation_data.action.fcurves:
                if fcurve.data_path == "location":
                    for kp in fcurve.keyframe_points:
                        kp.interpolation = camera_props.interpolation_mode
                    if camera_props.interpolation_mode == 'BEZIER':
                        cls._apply_bezier_smoothing(fcurve, camera_props.bezier_smoothness_factor)

        print(f"✅ Keyframe orbit created: {mode} from {start_frame} to {end_frame} with {camera_props.interpolation_mode} interpolation")
    @classmethod
    def parse_isodate_datetime(cls, value, include_time: bool = True):
        """Parsea fechas ISO (o datetime/date) y devuelve datetime sin microsegundos.
        - Acepta 'YYYY-MM-DD', 'YYYY-MM', 'YYYY', 'YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM]'.
        - Si include_time es False, se normaliza a 00:00:00.
        - Si no puede parsear, devuelve None.
        """
        try:
            import datetime as _dt, re as _re
            if value is None:
                return None
            if isinstance(value, _dt.datetime):
                return value.replace(microsecond=0) if include_time else value.replace(hour=0, minute=0, second=0, microsecond=0)
            if isinstance(value, _dt.date):
                return _dt.datetime.combine(value, _dt.time())
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return None
                # If contains time or timezone
                if 'T' in s or ' ' in s or 'Z' in s or '+' in s:
                    ss = s.replace(' ', 'T').replace('Z', '+00:00')
                    try:
                        dtv = _dt.datetime.fromisoformat(ss)
                    except ValueError:
                        # Try without seconds: YYYY-MM-DDTHH:MM
                        m = _re.match(r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})$', ss)
                        if m:
                            dtv = _dt.datetime.fromisoformat(m.group(1) + 'T' + m.group(2) + ':' + m.group(3) + ':00')
                        else:
                            return None
                    return dtv.replace(microsecond=0) if include_time else dtv.replace(hour=0, minute=0, second=0, microsecond=0)
                # Date-only variants
                try:
                    d = _dt.date.fromisoformat(s)
                except ValueError:
                    if _re.match(r'^\d{4}-\d{2}$', s):
                        y, m = s.split('-')
                        d = _dt.date(int(y), int(m), 1)
                    elif _re.match(r'^\d{4}$', s):
                        d = _dt.date(int(s), 1, 1)
                    else:
                        return None
                return _dt.datetime.combine(d, _dt.time())
            # Fallback
            return None
        except Exception:
            return None
    @classmethod
    def isodate_datetime(cls, value, include_time: bool = True) -> str:
        """
        Devuelve una cadena ISO-8601.
        - Si include_time es False => YYYY-MM-DD
        - Si include_time es True  => YYYY-MM-DDTHH:MM:SS (sin microsegundos)
        Acepta datetime/date o string y es tolerante a None.
        """
        try:
            import datetime as _dt
            if value is None:
                return ""
            # Si ya es str, devolver tal cual (se asume ISO o válido para UI)
            if isinstance(value, str):
                return value
            # Si es datetime/date
            if isinstance(value, _dt.datetime):
                return (value.replace(microsecond=0).isoformat()
                        if include_time else value.date().isoformat())
            if isinstance(value, _dt.date):
                return value.isoformat()
            # Cualquier otro tipo: intentar convertir
            return str(value)
        except Exception:
            return ""
    @classmethod
    def get_task_bar_list(cls) -> list[int]:
        """
        Obtiene la lista de IDs de tareas que deben mostrar barra visual.
        Retorna una lista de IDs de tareas.
        """
        props = cls.get_work_schedule_props()
        try:
            task_bars = json.loads(props.task_bars)
            return task_bars if isinstance(task_bars, list) else []
        except Exception:
            return []

    @classmethod
    def add_task_bar(cls, task_id: int) -> None:
        """Agrega una tarea a la lista de barras visuales."""
        props = cls.get_work_schedule_props()
        try:
            task_bars = json.loads(props.task_bars)
        except Exception:
            task_bars = []
        if task_id not in task_bars:
            task_bars.append(task_id)
            props.task_bars = json.dumps(task_bars)
            print(f"✅ Task {task_id} added to visual bars list")

    @classmethod
    def remove_task_bar(cls, task_id: int) -> None:
        """Remueve una tarea de la lista de barras visuales."""
        props = cls.get_work_schedule_props()
        try:
            task_bars = json.loads(props.task_bars)
        except Exception:
            task_bars = []
        if task_id in task_bars:
            task_bars.remove(task_id)
            props.task_bars = json.dumps(task_bars)
            print(f"❌ Task {task_id} removed from visual bars list")

    @classmethod
    def get_animation_bar_tasks(cls) -> list:
        """Obtiene las tareas IFC que tienen barras visuales habilitadas."""
        task_ids = cls.get_task_bar_list()
        tasks = []
        ifc_file = tool.Ifc.get()
        if ifc_file:
            for task_id in task_ids:
                try:
                    task = ifc_file.by_id(task_id)
                    if task and cls.validate_task_object(task, "get_animation_bar_tasks"):
                        tasks.append(task)
                except Exception as e:
                    print(f"⚠️ Error getting task {task_id}: {e}")
        return tasks

    @classmethod
    def refresh_task_bars(cls) -> None:
        """Actualiza la visualización de las barras de tareas en el viewport."""
        tasks = cls.get_animation_bar_tasks()
        if not tasks:
            print("⚠️ No tasks selected for bar visualization")
            if "Bar Visual" in bpy.data.collections:
                collection = bpy.data.collections["Bar Visual"]
                for obj in list(collection.objects):
                    bpy.data.objects.remove(obj)
            return
        cls.create_bars(tasks)
        print(f"✅ Created bars for {len(tasks)} tasks")



    @classmethod
    def get_work_schedule_props(cls) -> BIMWorkScheduleProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMWorkScheduleProperties  # pyright: ignore[reportAttributeAccessIssue]
    @classmethod
    def get_task_tree_props(cls) -> BIMTaskTreeProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMTaskTreeProperties  # pyright: ignore[reportAttributeAccessIssue]

    @classmethod
    def get_animation_props(cls) -> BIMAnimationProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMAnimationProperties  # pyright: ignore[reportAttributeAccessIssue]



    @classmethod
    def get_status_props(cls) -> BIMStatusProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMStatusProperties  # pyright: ignore[reportAttributeAccessIssue]



    @classmethod
    def get_work_plan_props(cls) -> BIMWorkPlanProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMWorkPlanProperties  # pyright: ignore[reportAttributeAccessIssue]

    @classmethod
    def get_work_calendar_props(cls) -> BIMWorkCalendarProperties:
        assert (scene := bpy.context.scene)
        return scene.BIMWorkCalendarProperties  # pyright: ignore[reportAttributeAccessIssue]

    @classmethod
    def get_work_plan_attributes(cls) -> dict[str, Any]:
        import bonsai.bim.module.sequence.helper as helper

        def callback(attributes: dict[str, Any], prop: Attribute) -> bool:
            if "Date" in prop.name or "Time" in prop.name:
                if prop.is_null:
                    attributes[prop.name] = None
                    return True
                attributes[prop.name] = helper.parse_datetime(prop.string_value)
                return True
            elif prop.name == "Duration" or prop.name == "TotalFloat":
                if prop.is_null:
                    attributes[prop.name] = None
                    return True
                attributes[prop.name] = helper.parse_duration(prop.string_value)
                return True
            return False

        props = cls.get_work_plan_props()
        return bonsai.bim.helper.export_attributes(props.work_plan_attributes, callback)

    @classmethod
    def load_work_plan_attributes(cls, work_plan: ifcopenshell.entity_instance) -> None:
        def callback(name: str, prop: Union[Attribute, None], data: dict[str, Any]) -> None | Literal[True]:
            if name in ["CreationDate", "StartTime", "FinishTime"]:
                assert prop
                prop.string_value = "" if prop.is_null else data[name]
                return True

        props = cls.get_work_plan_props()
        props.work_plan_attributes.clear()
        bonsai.bim.helper.import_attributes(work_plan, props.work_plan_attributes, callback)

    @classmethod
    def enable_editing_work_plan(cls, work_plan: Union[ifcopenshell.entity_instance, None]) -> None:
        if work_plan:
            props = cls.get_work_plan_props()
            props.active_work_plan_id = work_plan.id()
            props.editing_type = "ATTRIBUTES"

    @classmethod
    def disable_editing_work_plan(cls) -> None:
        props = cls.get_work_plan_props()
        props.active_work_plan_id = 0

    @classmethod
    def enable_editing_work_plan_schedules(cls, work_plan: Union[ifcopenshell.entity_instance, None]) -> None:
        if work_plan:
            props = cls.get_work_plan_props()
            props.active_work_plan_id = work_plan.id()
            props.editing_type = "SCHEDULES"

    @classmethod
    def get_work_schedule_attributes(cls) -> dict[str, Any]:
        import bonsai.bim.module.sequence.helper as helper

        def callback(attributes: dict[str, Any], prop: Attribute) -> bool:
            if "Date" in prop.name or "Time" in prop.name:
                if prop.is_null:
                    attributes[prop.name] = None
                    return True
                attributes[prop.name] = helper.parse_datetime(prop.string_value)
                return True
            elif prop.special_type == "DURATION":
                return cls.export_duration_prop(prop, attributes)
            return False

        props = cls.get_work_schedule_props()
        return bonsai.bim.helper.export_attributes(props.work_schedule_attributes, callback)

    @classmethod
    def load_work_schedule_attributes(cls, work_schedule: ifcopenshell.entity_instance) -> None:
        schema = tool.Ifc.schema()
        entity = schema.declaration_by_name("IfcWorkSchedule").as_entity()
        assert entity

        def callback(name: str, prop: Union[Attribute, None], data: dict[str, Any]) -> None | Literal[True]:
            if name in ["CreationDate", "StartTime", "FinishTime"]:
                assert prop
                prop.string_value = "" if prop.is_null else data[name]
                return True
            else:
                attr = entity.attribute_by_index(entity.attribute_index(name))
                if not attr.type_of_attribute()._is("IfcDuration"):
                    return
                assert prop
                cls.add_duration_prop(prop, data[name])

        props = cls.get_work_schedule_props()
        props.work_schedule_attributes.clear()
        bonsai.bim.helper.import_attributes(work_schedule, props.work_schedule_attributes, callback)

    @classmethod
    def add_duration_prop(cls, prop: Attribute, duration_value: Union[str, None]) -> None:
        import bonsai.bim.module.sequence.helper as helper

        props = cls.get_work_schedule_props()
        prop.special_type = "DURATION"
        duration_props = props.durations_attributes.add()
        duration_props.name = prop.name
        if duration_value is None:
            return
        for key, value in helper.parse_duration_as_blender_props(duration_value).items():
            setattr(duration_props, key, value)

    @classmethod
    def export_duration_prop(cls, prop: Attribute, out_attributes: dict[str, Any]) -> Literal[True]:
        import bonsai.bim.module.sequence.helper as helper

        props = cls.get_work_schedule_props()
        if prop.is_null:
            out_attributes[prop.name] = None
        else:
            duration_type = out_attributes["DurationType"] if "DurationType" in out_attributes else None
            time_split_iso_duration = helper.blender_props_to_iso_duration(
                props.durations_attributes, duration_type, prop.name
            )
            out_attributes[prop.name] = time_split_iso_duration
        return True

    @classmethod
    def enable_editing_work_schedule(cls, work_schedule: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_work_schedule_id = work_schedule.id()
        props.editing_type = "WORK_SCHEDULE"

    @classmethod
    def disable_editing_work_schedule(cls) -> None:
        props = cls.get_work_schedule_props()
        props.active_work_schedule_id = 0

    @classmethod
    def enable_editing_work_schedule_tasks(cls, work_schedule: Union[ifcopenshell.entity_instance, None]) -> None:
        if work_schedule:
            props = cls.get_work_schedule_props()
            props.active_work_schedule_id = work_schedule.id()
            props.editing_type = "TASKS"

    
    
    @classmethod
    def load_task_tree(cls, work_schedule: ifcopenshell.entity_instance) -> None:
        props = cls.get_task_tree_props()
        props.tasks.clear()
        schedule_props = cls.get_work_schedule_props()
        cls.contracted_tasks = json.loads(schedule_props.contracted_tasks)

        # 1. Obtener TODAS las tareas raíz, como antes
        root_tasks = ifcopenshell.util.sequence.get_root_tasks(work_schedule)
        
        # 2. APLICAR FILTRO: Pasar la lista de tareas raíz a nuestra nueva función de filtrado
        filtered_root_tasks = cls.get_filtered_tasks(root_tasks)

        # 3. Ordenar solo las tareas que pasaron el filtro
        related_objects_ids = cls.get_sorted_tasks_ids(filtered_root_tasks)
        
        # 4. Crear los elementos de la UI solo para las tareas filtradas y ordenadas
        for related_object_id in related_objects_ids:
            cls.create_new_task_li(related_object_id, 0)

    @classmethod
    def get_sorted_tasks_ids(cls, tasks: list[ifcopenshell.entity_instance]) -> list[int]:
        props = cls.get_work_schedule_props()

        def get_sort_key(task):
            # Sorting only applies to actual tasks, not the WBS
            # for rel in task.IsNestedBy:
            #     for object in rel.RelatedObjects:
            #         if object.is_a("IfcTask"):
            #             return "0000000000" + (task.Identification or "")
            column_type, name = props.sort_column.split(".")
            if column_type == "IfcTask":
                return task.get_info(task)[name] or ""
            elif column_type == "IfcTaskTime" and task.TaskTime:
                return task.TaskTime.get_info(task)[name] if task.TaskTime.get_info(task)[name] else ""
            return task.Identification or ""

        def natural_sort_key(i, _nsre=re.compile("([0-9]+)")):
            s = sort_keys[i]
            return [int(text) if text.isdigit() else text.lower() for text in _nsre.split(s)]

        if props.sort_column:
            sort_keys = {task.id(): get_sort_key(task) for task in tasks}
            related_object_ids = sorted(sort_keys, key=natural_sort_key)
        else:
            related_object_ids = [task.id() for task in tasks]
        if props.is_sort_reversed:
            related_object_ids.reverse()
        return related_object_ids

    

    @classmethod
    def get_filtered_tasks(cls, tasks: list[ifcopenshell.entity_instance]) -> list[ifcopenshell.entity_instance]:
        """
        Filtra una lista de tareas (y sus hijos) basándose en las reglas activas.
        Si una tarea padre no cumple el filtro, sus hijos tampoco se mostrarán.
        """
        props = cls.get_work_schedule_props()
        try:
            filter_rules = [r for r in getattr(props, "filters").rules if r.is_active]
        except Exception:
            return tasks

        if not filter_rules:
            return tasks

        filter_logic_is_and = getattr(props.filters, "logic", 'AND') == 'AND'
        
        def get_task_value(task, column_identifier):
            """Función auxiliar mejorada para obtener el valor de una columna para una tarea."""
            if not task or not column_identifier:
                return None
            
            column_name = column_identifier.split('||')[0]

            if column_name == "Special.OutputsCount":
                try:
                    # Usa la función de utilidad de ifcopenshell para obtener los outputs
                    return len(ifcopenshell.util.sequence.get_task_outputs(task, is_deep=False))
                except Exception:
                    return 0
            
            try:
                ifc_class, attr_name = column_name.split('.', 1)
                if ifc_class == "IfcTask":
                    return getattr(task, attr_name, None)
                elif ifc_class == "IfcTaskTime":
                    task_time = getattr(task, "TaskTime", None)
                    return getattr(task_time, attr_name, None) if task_time else None
            except Exception:
                return None
            return None

        def task_matches_filters(task):
            """Comprueba si una única tarea cumple con el conjunto de filtros."""
            results = []
            for rule in filter_rules:
                task_value = get_task_value(task, rule.column)
                data_type = getattr(rule, 'data_type', 'string')
                op = rule.operator
                match = False

                if op == 'EMPTY':
                    match = task_value is None or str(task_value).strip() == ""
                elif op == 'NOT_EMPTY':
                    match = task_value is not None and str(task_value).strip() != ""
                else:
                    try:
                        if data_type == 'integer':
                            rule_value = rule.value_integer
                            task_value_num = int(task_value)
                            if op == 'EQUALS': match = task_value_num == rule_value
                            elif op == 'NOT_EQUALS': match = task_value_num != rule_value
                            elif op == 'GREATER': match = task_value_num > rule_value
                            elif op == 'LESS': match = task_value_num < rule_value
                            elif op == 'GTE': match = task_value_num >= rule_value
                            elif op == 'LTE': match = task_value_num <= rule_value
                        elif data_type in ('float', 'real'):
                            rule_value = rule.value_float
                            task_value_num = float(task_value)
                            if op == 'EQUALS': match = task_value_num == rule_value
                            elif op == 'NOT_EQUALS': match = task_value_num != rule_value
                            elif op == 'GREATER': match = task_value_num > rule_value
                            elif op == 'LESS': match = task_value_num < rule_value
                            elif op == 'GTE': match = task_value_num >= rule_value
                            elif op == 'LTE': match = task_value_num <= rule_value
                        elif data_type == 'boolean':
                            rule_value = bool(rule.value_boolean)
                            task_value_bool = bool(task_value)
                            if op == 'EQUALS': match = task_value_bool == rule_value
                            elif op == 'NOT_EQUALS': match = task_value_bool != rule_value
                        elif data_type == 'date':
                            task_date = bonsai.bim.module.sequence.helper.parse_datetime(str(task_value))
                            rule_date = bonsai.bim.module.sequence.helper.parse_datetime(rule.value_string)
                            if task_date and rule_date:
                                if op == 'EQUALS': match = task_date.date() == rule_date.date()
                                elif op == 'NOT_EQUALS': match = task_date.date() != rule_date.date()
                                elif op == 'GREATER': match = task_date > rule_date
                                elif op == 'LESS': match = task_date < rule_date
                                elif op == 'GTE': match = task_date >= rule_date
                                elif op == 'LTE': match = task_date <= rule_date
                        else: # string, enums, etc.
                            rule_value = (rule.value_string or "").lower()
                            task_value_str = (str(task_value) if task_value is not None else "").lower()
                            if op == 'CONTAINS': match = rule_value in task_value_str
                            elif op == 'NOT_CONTAINS': match = rule_value not in task_value_str
                            elif op == 'EQUALS': match = rule_value == task_value_str
                            elif op == 'NOT_EQUALS': match = rule_value != task_value_str
                    except (ValueError, TypeError, AttributeError):
                        match = False
                results.append(match)

            if not results: 
                return True
            return all(results) if filter_logic_is_and else any(results)

        filtered_list = []
        for task in tasks:
            nested_tasks = ifcopenshell.util.sequence.get_nested_tasks(task)
            filtered_children = cls.get_filtered_tasks(nested_tasks) if nested_tasks else []

            if task_matches_filters(task) or len(filtered_children) > 0:
                filtered_list.append(task)
                
        return filtered_list

    @classmethod
    def create_new_task_li(cls, related_object_id: int, level_index: int) -> None:
        task = tool.Ifc.get().by_id(related_object_id)
        props = cls.get_task_tree_props()
        new = props.tasks.add()
        new.ifc_definition_id = related_object_id
        new.is_expanded = related_object_id not in cls.contracted_tasks
        new.level_index = level_index
        if task.IsNestedBy:
            new.has_children = True
            if new.is_expanded:
                for related_object_id in cls.get_sorted_tasks_ids(ifcopenshell.util.sequence.get_nested_tasks(task)):
                    cls.create_new_task_li(related_object_id, level_index + 1)

    # TODO: task argument is never used?
    @classmethod
    def load_task_properties(cls, task: Optional[ifcopenshell.entity_instance] = None) -> None:
        props = cls.get_work_schedule_props()
        task_props = cls.get_task_tree_props()
        tasks_with_visual_bar = cls.get_task_bar_list()
        props.is_task_update_enabled = False

        for item in task_props.tasks:
            task = tool.Ifc.get().by_id(item.ifc_definition_id)
            item.name = task.Name or "Unnamed"
            item.identification = task.Identification or "XXX"
            item.has_bar_visual = item.ifc_definition_id in tasks_with_visual_bar
            if props.highlighted_task_id:
                item.is_predecessor = props.highlighted_task_id in [
                    rel.RelatedProcess.id() for rel in task.IsPredecessorTo
                ]
                item.is_successor = props.highlighted_task_id in [
                    rel.RelatingProcess.id() for rel in task.IsSuccessorFrom
                ]
            calendar = ifcopenshell.util.sequence.derive_calendar(task)
            if ifcopenshell.util.sequence.get_calendar(task):
                item.calendar = calendar.Name or "Unnamed" if calendar else ""
            else:
                item.calendar = ""
                item.derived_calendar = calendar.Name or "Unnamed" if calendar else ""

            if task.TaskTime and (
                task.TaskTime.ScheduleStart or task.TaskTime.ScheduleFinish or task.TaskTime.ScheduleDuration
            ):
                task_time = task.TaskTime
                item.start = (
                    ifcopenshell.util.date.canonicalise_time(
                        ifcopenshell.util.date.ifc2datetime(task_time.ScheduleStart)
                    )
                    if task_time.ScheduleStart
                    else "-"
                )
                item.finish = (
                    ifcopenshell.util.date.canonicalise_time(
                        ifcopenshell.util.date.ifc2datetime(task_time.ScheduleFinish)
                    )
                    if task_time.ScheduleFinish
                    else "-"
                )
                item.duration = (
                    str(ifcopenshell.util.date.readable_ifc_duration(task_time.ScheduleDuration))
                    if task_time.ScheduleDuration
                    else "-"
                )
            else:
                derived_start = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
                derived_finish = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)
                item.derived_start = ifcopenshell.util.date.canonicalise_time(derived_start) if derived_start else ""
                item.derived_finish = ifcopenshell.util.date.canonicalise_time(derived_finish) if derived_finish else ""
                if derived_start and derived_finish:
                    derived_duration = ifcopenshell.util.sequence.count_working_days(
                        derived_start, derived_finish, calendar
                    )
                    item.derived_duration = str(ifcopenshell.util.date.readable_ifc_duration(f"P{derived_duration}D"))
                item.start = "-"
                item.finish = "-"
                item.duration = "-"

        # After processing all tasks, refresh the Outputs count so UI stays accurate.
        try:
            cls.refresh_task_output_counts()
        except Exception:
            # Be defensive; never break UI loading if counting fails.
            pass

        props.is_task_update_enabled = True

    @classmethod
    def refresh_task_output_counts(cls) -> None:
        """
        Recalcula y guarda (si existe) el conteo de Outputs por tarea en el árbol actual.
        Es seguro: si los atributos/propiedades no existen, simplemente no hace nada.
        """
        try:
            tprops = cls.get_task_tree_props()
        except Exception:
            return
        try:
            from bonsai import tool as _tool
            import ifcopenshell  # type: ignore
        except Exception:
            # Si los módulos no están disponibles en este contexto, salimos silenciosamente.
            return
        for item in getattr(tprops, "tasks", []):
            try:
                task = _tool.Ifc.get().by_id(item.ifc_definition_id)
                count = len(ifcopenshell.util.sequence.get_task_outputs(task, is_deep=False)) if task else 0
                if hasattr(item, "outputs_count"):
                    # Algunas builds definen este atributo en el item del árbol
                    setattr(item, "outputs_count", count)
                # En otros casos el recuento se utiliza de forma dinámica (p.ej. en columnas),
                # por lo que no es necesario almacenar nada; el cálculo anterior actúa como verificación.
            except Exception:
                # Nunca interrumpir la UI por errores de tareas individuales.
                continue


    @classmethod
    def get_active_work_schedule(cls) -> Union[ifcopenshell.entity_instance, None]:
        props = cls.get_work_schedule_props()
        if not props.active_work_schedule_id:
            return None
        return tool.Ifc.get().by_id(props.active_work_schedule_id)

    @classmethod
    def expand_task(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        contracted_tasks = json.loads(props.contracted_tasks)
        contracted_tasks.remove(task.id())
        props.contracted_tasks = json.dumps(contracted_tasks)

    @classmethod
    def expand_all_tasks(cls) -> None:
        props = cls.get_work_schedule_props()
        props.contracted_tasks = json.dumps([])

    @classmethod
    def contract_all_tasks(cls) -> None:
        props = cls.get_work_schedule_props()
        tprops = cls.get_task_tree_props()
        contracted_tasks = json.loads(props.contracted_tasks)
        for task_item in tprops.tasks:
            if task_item.is_expanded:
                contracted_tasks.append(task_item.ifc_definition_id)
        props.contracted_tasks = json.dumps(contracted_tasks)

    @classmethod
    def contract_task(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        contracted_tasks = json.loads(props.contracted_tasks)
        contracted_tasks.append(task.id())
        props.contracted_tasks = json.dumps(contracted_tasks)

    @classmethod
    def disable_work_schedule(cls) -> None:
        props = cls.get_work_schedule_props()
        props.active_work_schedule_id = 0

    @classmethod
    def disable_selecting_deleted_task(cls) -> None:
        props = cls.get_work_schedule_props()
        if props.active_task_id not in [
            task.ifc_definition_id for task in cls.get_task_tree_props().tasks
        ]:  # Task was deleted
            props.active_task_id = 0
            props.active_task_time_id = 0

    @classmethod
    def get_checked_tasks(cls) -> list[ifcopenshell.entity_instance]:
        return [
            tool.Ifc.get().by_id(task.ifc_definition_id) for task in cls.get_task_tree_props().tasks if task.is_selected
        ] or []

    @classmethod
    def get_task_attribute_value(cls, attribute_name: str) -> Any:
        props = cls.get_work_schedule_props()
        return props.task_attributes[attribute_name].get_value()

    @classmethod
    def get_active_task(cls) -> ifcopenshell.entity_instance:
        props = cls.get_work_schedule_props()
        return tool.Ifc.get().by_id(props.active_task_id)

    @classmethod
    def get_active_work_time(cls) -> ifcopenshell.entity_instance:
        props = cls.get_work_calendar_props()
        return tool.Ifc.get().by_id(props.active_work_time_id)

    @classmethod
    def get_task_time(cls, task: ifcopenshell.entity_instance) -> Union[ifcopenshell.entity_instance, None]:
        return task.TaskTime or None

    @classmethod
    def load_task_attributes(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.task_attributes.clear()
        bonsai.bim.helper.import_attributes(task, props.task_attributes)

    @classmethod
    def enable_editing_task_attributes(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_task_id = task.id()
        props.editing_task_type = "ATTRIBUTES"

    @classmethod
    def get_task_attributes(cls) -> dict[str, Any]:
        props = cls.get_work_schedule_props()
        return bonsai.bim.helper.export_attributes(props.task_attributes)

    @classmethod
    def load_task_time_attributes(cls, task_time: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        schema = tool.Ifc.schema()
        entity = schema.declaration_by_name("IfcTaskTime").as_entity()
        assert entity

        def callback(name: str, prop: Union[Attribute, None], data: dict[str, Any]) -> Union[bool, None]:
            attr = entity.attribute_by_index(entity.attribute_index(name))
            if attr.type_of_attribute()._is("IfcDuration"):
                assert prop
                cls.add_duration_prop(prop, data[name])
            if isinstance(data[name], datetime):
                assert prop
                prop.string_value = "" if prop.is_null else data[name].isoformat()
                return True

        props.task_time_attributes.clear()
        props.durations_attributes.clear()
        bonsai.bim.helper.import_attributes(task_time, props.task_time_attributes, callback)

    @classmethod
    def enable_editing_task_time(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_task_id = task.id()
        props.active_task_time_id = task.TaskTime.id()
        props.editing_task_type = "TASKTIME"

    @classmethod
    def disable_editing_task(cls) -> None:
        props = cls.get_work_schedule_props()
        props.active_task_id = 0
        props.active_task_time_id = 0
        props.editing_task_type = ""

    @classmethod
    def get_task_time_attributes(cls) -> dict[str, Any]:
        import bonsai.bim.module.sequence.helper as helper

        props = cls.get_work_schedule_props()

        def callback(attributes: dict[str, Any], prop: Attribute) -> bool:
            if "Start" in prop.name or "Finish" in prop.name or prop.name == "StatusTime":
                if prop.is_null:
                    attributes[prop.name] = None
                    return True
                attributes[prop.name] = helper.parse_datetime(prop.string_value)
                return True
            elif prop.special_type == "DURATION":
                return cls.export_duration_prop(prop, attributes)
            return False

        return bonsai.bim.helper.export_attributes(props.task_time_attributes, callback)

    @classmethod
    def load_task_resources(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        rprops = tool.Resource.get_resource_props()
        props.task_resources.clear()
        rprops.is_resource_update_enabled = False
        for resource in cls.get_task_resources(task) or []:
            new = props.task_resources.add()
            new.ifc_definition_id = resource.id()
            new.name = resource.Name or "Unnamed"
            new.schedule_usage = resource.Usage.ScheduleUsage or 0 if resource.Usage else 0
        rprops.is_resource_update_enabled = True

    @classmethod
    def get_task_inputs(cls, task: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        props = cls.get_work_schedule_props()
        is_deep = props.show_nested_inputs
        return ifcopenshell.util.sequence.get_task_inputs(task, is_deep)

    @classmethod
    def get_task_outputs(cls, task: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        props = cls.get_work_schedule_props()
        is_deep = props.show_nested_outputs
        return ifcopenshell.util.sequence.get_task_outputs(task, is_deep)

    @classmethod
    def are_entities_same_class(cls, entities: list[ifcopenshell.entity_instance]) -> bool:
        if not entities:
            return False
        if len(entities) == 1:
            return True
        first_class = entities[0].is_a()
        for entity in entities:
            if entity.is_a() != first_class:
                return False
        return True

    @classmethod
    def get_task_resources(
        cls, task: Union[ifcopenshell.entity_instance, None]
    ) -> Union[list[ifcopenshell.entity_instance], None]:
        if not task:
            return
        props = cls.get_work_schedule_props()
        is_deep = props.show_nested_resources
        return ifcopenshell.util.sequence.get_task_resources(task, is_deep)

    @classmethod
    def load_task_inputs(cls, inputs: list[ifcopenshell.entity_instance]) -> None:
        props = cls.get_work_schedule_props()
        props.task_inputs.clear()
        for input in inputs:
            new = props.task_inputs.add()
            new.ifc_definition_id = input.id()
            new.name = input.Name or "Unnamed"

    @classmethod
    def load_task_outputs(cls, outputs: list[ifcopenshell.entity_instance]) -> None:
        props = cls.get_work_schedule_props()
        props.task_outputs.clear()
        if outputs:
            for output in outputs:
                new = props.task_outputs.add()
                new.ifc_definition_id = output.id()
                new.name = output.Name or "Unnamed"

    @classmethod
    def get_highlighted_task(cls) -> Union[ifcopenshell.entity_instance, None]:
        tasks = cls.get_task_tree_props().tasks
        props = cls.get_work_schedule_props()
        if len(tasks) and len(tasks) > props.active_task_index:
            return tool.Ifc.get().by_id(tasks[props.active_task_index].ifc_definition_id)

    @classmethod
    def get_direct_nested_tasks(cls, task: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        return ifcopenshell.util.sequence.get_nested_tasks(task)

    @classmethod
    def get_direct_task_outputs(cls, task: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        return ifcopenshell.util.sequence.get_direct_task_outputs(task)

    @classmethod
    def enable_editing_work_calendar_times(cls, work_calendar: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_calendar_props()
        props.active_work_calendar_id = work_calendar.id()
        props.editing_type = "WORKTIMES"

    @classmethod
    def load_work_calendar_attributes(cls, work_calendar: ifcopenshell.entity_instance) -> dict[str, Any]:
        props = cls.get_work_calendar_props()
        props.work_calendar_attributes.clear()
        return bonsai.bim.helper.import_attributes(work_calendar, props.work_calendar_attributes)

    @classmethod
    def enable_editing_work_calendar(cls, work_calendar: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_calendar_props()
        props.active_work_calendar_id = work_calendar.id()
        props.editing_type = "ATTRIBUTES"

    @classmethod
    def disable_editing_work_calendar(cls) -> None:
        props = cls.get_work_calendar_props()
        props.active_work_calendar_id = 0

    @classmethod
    def get_work_calendar_attributes(cls) -> dict[str, Any]:
        props = cls.get_work_calendar_props()
        return bonsai.bim.helper.export_attributes(props.work_calendar_attributes)

    @classmethod
    def load_work_time_attributes(cls, work_time: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_calendar_props()
        props.work_time_attributes.clear()

        bonsai.bim.helper.import_attributes(work_time, props.work_time_attributes)

    @classmethod
    def enable_editing_work_time(cls, work_time: ifcopenshell.entity_instance) -> None:
        def initialise_recurrence_components(props):
            if len(props.day_components) == 0:
                for i in range(0, 31):
                    new = props.day_components.add()
                    new.name = str(i + 1)
            if len(props.weekday_components) == 0:
                for d in ["M", "T", "W", "T", "F", "S", "S"]:
                    new = props.weekday_components.add()
                    new.name = d
            if len(props.month_components) == 0:
                for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
                    new = props.month_components.add()
                    new.name = m

        def load_recurrence_pattern_data(work_time, props):
            props.position = 0
            props.interval = 0
            props.occurrences = 0
            props.start_time = ""
            props.end_time = ""
            for component in props.day_components:
                component.is_specified = False
            for component in props.weekday_components:
                component.is_specified = False
            for component in props.month_components:
                component.is_specified = False
            if not work_time.RecurrencePattern:
                return
            recurrence_pattern = work_time.RecurrencePattern
            for attribute in ["Position", "Interval", "Occurrences"]:
                if getattr(recurrence_pattern, attribute):
                    setattr(props, attribute.lower(), getattr(recurrence_pattern, attribute))
            for component in recurrence_pattern.DayComponent or []:
                props.day_components[component - 1].is_specified = True
            for component in recurrence_pattern.WeekdayComponent or []:
                props.weekday_components[component - 1].is_specified = True
            for component in recurrence_pattern.MonthComponent or []:
                props.month_components[component - 1].is_specified = True

        props = cls.get_work_calendar_props()
        initialise_recurrence_components(props)
        load_recurrence_pattern_data(work_time, props)
        props.active_work_time_id = work_time.id()
        props.editing_type = "WORKTIMES"

    @classmethod
    def get_work_time_attributes(cls) -> dict[str, Any]:
        import bonsai.bim.module.sequence.helper as helper

        def callback(attributes: dict[str, Any], prop: Attribute) -> bool:
            if "Start" in prop.name or "Finish" in prop.name:
                if prop.is_null:
                    attributes[prop.name] = None
                    return True
                attributes[prop.name] = helper.parse_datetime(prop.string_value)
                return True
            return False

        props = cls.get_work_calendar_props()
        return bonsai.bim.helper.export_attributes(props.work_time_attributes, callback)

    @classmethod
    def get_recurrence_pattern_attributes(cls, recurrence_pattern):
        props = cls.get_work_calendar_props()
        attributes = {
            "Interval": props.interval if props.interval > 0 else None,
            "Occurrences": props.occurrences if props.occurrences > 0 else None,
        }
        applicable_data = {
            "DAILY": ["Interval", "Occurrences"],
            "WEEKLY": ["WeekdayComponent", "Interval", "Occurrences"],
            "MONTHLY_BY_DAY_OF_MONTH": ["DayComponent", "Interval", "Occurrences"],
            "MONTHLY_BY_POSITION": ["WeekdayComponent", "Position", "Interval", "Occurrences"],
            "BY_DAY_COUNT": ["Interval", "Occurrences"],
            "BY_WEEKDAY_COUNT": ["WeekdayComponent", "Interval", "Occurrences"],
            "YEARLY_BY_DAY_OF_MONTH": ["DayComponent", "MonthComponent", "Interval", "Occurrences"],
            "YEARLY_BY_POSITION": ["WeekdayComponent", "MonthComponent", "Position", "Interval", "Occurrences"],
        }
        if "Position" in applicable_data[recurrence_pattern.RecurrenceType]:
            attributes["Position"] = props.position if props.position != 0 else None
        if "DayComponent" in applicable_data[recurrence_pattern.RecurrenceType]:
            attributes["DayComponent"] = [i + 1 for i, c in enumerate(props.day_components) if c.is_specified]
        if "WeekdayComponent" in applicable_data[recurrence_pattern.RecurrenceType]:
            attributes["WeekdayComponent"] = [i + 1 for i, c in enumerate(props.weekday_components) if c.is_specified]
        if "MonthComponent" in applicable_data[recurrence_pattern.RecurrenceType]:
            attributes["MonthComponent"] = [i + 1 for i, c in enumerate(props.month_components) if c.is_specified]
        return attributes

    @classmethod
    def disable_editing_work_time(cls) -> None:
        props = cls.get_work_calendar_props()
        props.active_work_time_id = 0

    @classmethod
    def get_recurrence_pattern_times(cls) -> Union[tuple[datetime, datetime], None]:
        props = cls.get_work_calendar_props()
        try:
            start_time = parser.parse(props.start_time)
            end_time = parser.parse(props.end_time)
            return start_time, end_time
        except:
            return  # improve UI / refactor to add user hints

    @classmethod
    def reset_time_period(cls) -> None:
        props = cls.get_work_calendar_props()
        props.start_time = ""
        props.end_time = ""

    @classmethod
    def enable_editing_task_calendar(cls, task: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_task_id = task.id()
        props.editing_task_type = "CALENDAR"

    @classmethod
    def enable_editing_task_sequence(cls) -> None:
        props = cls.get_work_schedule_props()
        props.editing_task_type = "SEQUENCE"

    @classmethod
    def disable_editing_task_time(cls) -> None:
        props = cls.get_work_schedule_props()
        props.active_task_id = 0
        props.active_task_time_id = 0

    @classmethod
    def load_rel_sequence_attributes(cls, rel_sequence: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.sequence_attributes.clear()
        bonsai.bim.helper.import_attributes(rel_sequence, props.sequence_attributes)

    @classmethod
    def enable_editing_rel_sequence_attributes(cls, rel_sequence: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_sequence_id = rel_sequence.id()
        props.editing_sequence_type = "ATTRIBUTES"

    @classmethod
    def load_lag_time_attributes(cls, lag_time: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()

        def callback(name: str, prop: Union[Attribute, None], data: dict[str, Any]) -> None | Literal[True]:
            if name == "LagValue":
                prop = props.lag_time_attributes.add()
                prop.name = name
                prop.is_null = data[name] is None
                prop.is_optional = False
                prop.data_type = "string"
                prop.string_value = (
                    "" if prop.is_null else ifcopenshell.util.date.datetime2ifc(data[name].wrappedValue, "IfcDuration")
                )
                return True

        props.lag_time_attributes.clear()
        bonsai.bim.helper.import_attributes(lag_time, props.lag_time_attributes, callback)

    @classmethod
    def enable_editing_sequence_lag_time(cls, rel_sequence: ifcopenshell.entity_instance) -> None:
        props = cls.get_work_schedule_props()
        props.active_sequence_id = rel_sequence.id()
        props.editing_sequence_type = "LAG_TIME"

    @classmethod
    def get_rel_sequence_attributes(cls) -> dict[str, Any]:
        props = cls.get_work_schedule_props()
        return bonsai.bim.helper.export_attributes(props.sequence_attributes)

    @classmethod
    def disable_editing_rel_sequence(cls) -> None:
        props = cls.get_work_schedule_props()
        props.active_sequence_id = 0

    @classmethod
    def get_lag_time_attributes(cls) -> dict[str, Any]:
        props = cls.get_work_schedule_props()
        return bonsai.bim.helper.export_attributes(props.lag_time_attributes)

    @classmethod
    def select_products(cls, products: Iterable[ifcopenshell.entity_instance]) -> None:
        [obj.select_set(False) for obj in bpy.context.selected_objects]
        for product in products:
            obj = tool.Ifc.get_object(product)
            obj.select_set(True) if obj else None

    @classmethod
    def add_task_column(cls, column_type: str, name: str, data_type: str) -> None:
        props = cls.get_work_schedule_props()
        new = props.columns.add()
        new.name = f"{column_type}.{name}"
        new.data_type = data_type

    @classmethod
    def setup_default_task_columns(cls) -> None:
        props = cls.get_work_schedule_props()
        props.columns.clear()
        default_columns = ["ScheduleStart", "ScheduleFinish", "ScheduleDuration"]
        for item in default_columns:
            new = props.columns.add()
            new.name = f"IfcTaskTime.{item}"
            new.data_type = "string"

    @classmethod
    def remove_task_column(cls, name: str) -> None:
        props = cls.get_work_schedule_props()
        props.columns.remove(props.columns.find(name))
        if props.sort_column == name:
            props.sort_column = ""

    @classmethod
    def set_task_sort_column(cls, column: str) -> None:
        props = cls.get_work_schedule_props()
        props.sort_column = column

    @classmethod
    def find_related_input_tasks(cls, product):
        related_tasks = []
        for assignment in product.HasAssignments:
            if assignment.is_a("IfcRelAssignsToProcess") and assignment.RelatingProcess.is_a("IfcTask"):
                related_tasks.append(assignment.RelatingProcess)
        return related_tasks

    @classmethod
    def find_related_output_tasks(cls, product):
        related_tasks = []
        for reference in product.ReferencedBy:
            if reference.is_a("IfcRelAssignsToProduct") and reference.RelatedObjects[0].is_a("IfcTask"):
                related_tasks.append(reference.RelatedObjects[0])
        return related_tasks

    @classmethod
    def get_work_schedule(cls, task: ifcopenshell.entity_instance) -> Union[ifcopenshell.entity_instance, None]:
        for rel in task.HasAssignments or []:
            if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl.is_a("IfcWorkSchedule"):
                return rel.RelatingControl
        for rel in task.Nests or []:
            return cls.get_work_schedule(rel.RelatingObject)

    @classmethod
    def is_work_schedule_active(cls, work_schedule):
        props = cls.get_work_schedule_props()
        return True if work_schedule.id() == props.active_work_schedule_id else False

    @classmethod
    def go_to_task(cls, task):
        props = cls.get_work_schedule_props()

        def get_ancestor_ids(task):
            ids = []
            for rel in task.Nests or []:
                ids.append(rel.RelatingObject.id())
                ids.extend(get_ancestor_ids(rel.RelatingObject))
            return ids

        contracted_tasks = json.loads(props.contracted_tasks)
        for ancestor_id in get_ancestor_ids(task):
            if ancestor_id in contracted_tasks:
                contracted_tasks.remove(ancestor_id)
        props.contracted_tasks = json.dumps(contracted_tasks)

        work_schedule = cls.get_active_work_schedule()
        cls.load_task_tree(work_schedule)
        cls.load_task_properties()

        task_props = cls.get_task_tree_props()
        expanded_tasks = [item.ifc_definition_id for item in task_props.tasks]
        props.active_task_index = expanded_tasks.index(task.id()) or 0

    # TODO: proper typing
    @classmethod
    def guess_date_range(cls, work_schedule: ifcopenshell.entity_instance) -> tuple[Any, Any]:
        return ifcopenshell.util.sequence.guess_date_range(work_schedule)


    @classmethod
    def get_schedule_date_range(cls, work_schedule=None):
        """
        Obtiene el rango de fechas REAL del cronograma activo (no las fechas de visualización).

        Returns:
            tuple: (schedule_start: datetime, schedule_finish: datetime) o (None, None) si falla
        """
        try:
            if not work_schedule:
                work_schedule = cls.get_active_work_schedule()

            if not work_schedule:
                print("⚠️ No hay cronograma activo para obtener fechas")
                return None, None

            # Usar la función existente para inferir fechas del cronograma
            schedule_start = None
            schedule_finish = None
            try:
                infer = getattr(cls, "_infer_schedule_date_range", None)
                if infer:
                    schedule_start, schedule_finish = infer(work_schedule)
            except Exception as e:
                print(f"⚠️ Error en _infer_schedule_date_range: {e}")

            if schedule_start and schedule_finish:
                print(f"📅 Schedule dates: {schedule_start.strftime('%Y-%m-%d')} to {schedule_finish.strftime('%Y-%m-%d')}")
                return schedule_start, schedule_finish

            # Fallback: usar guess_date_range
            try:
                schedule_start, schedule_finish = cls.guess_date_range(work_schedule)
                if schedule_start and schedule_finish:
                    return schedule_start, schedule_finish
            except Exception as e:
                print(f"⚠️ Error en guess_date_range: {e}")

            print("⚠️ No se pudieron determinar las fechas del cronograma")
            return None, None

        except Exception as e:
            print(f"❌ Error obteniendo fechas del cronograma: {e}")
            return None, None

    @classmethod
    def update_visualisation_date(cls, start_date, finish_date):
        if not (start_date and finish_date):
            return
        props = cls.get_work_schedule_props()
        props.visualisation_start = ifcopenshell.util.date.canonicalise_time(start_date)
        props.visualisation_finish = ifcopenshell.util.date.canonicalise_time(finish_date)
    @classmethod
    def create_bars(cls, tasks):
        full_bar_thickness = 0.2
        size = 1.0
        vertical_spacing = 3.5
        vertical_increment = 0
        size_to_duration_ratio = 1 / 30
        margin = 0.2

        # VALIDACIÓN: Filtrar tareas inválidas antes de cualquier uso
        if tasks:
            _valid = []
            for _t in tasks:
                if cls.validate_task_object(_t, "create_bars"):
                    _valid.append(_t)
                else:
                    print(f"⚠️ Skipping invalid task in create_bars: {_t}")
            if not _valid:
                print("⚠️ Warning: No valid tasks found for bar creation")
                return
            tasks = _valid
        else:
            print("⚠️ Warning: No tasks provided to create_bars")
            return


        def process_task_data(task, settings):
            # VALIDACIÓN CRÍTICA: verificar tarea válida
            if not cls.validate_task_object(task, "process_task_data"):
                return None

            try:
                task_start_date = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
                finish_date = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)
            except Exception as e:
                print(f"⚠️ Error deriving dates for task {getattr(task, 'Name', 'Unknown')}: {e}")
                return None

            if not (task_start_date and finish_date):
                print(f"⚠️ Warning: Task {getattr(task, 'Name', 'Unknown')} has no valid dates")
                return None

            try:
                # CORRECCIÓN: Usar las fechas del cronograma para cálculos
                schedule_start = settings["viz_start"]
                schedule_finish = settings["viz_finish"]
                schedule_duration = schedule_finish - schedule_start

                if schedule_duration.total_seconds() <= 0:
                    print(f"⚠️ Invalid schedule duration: {schedule_duration}")
                    return None

                total_frames = settings["end_frame"] - settings["start_frame"]

                # Calcular posición de la tarea dentro del cronograma completo
                task_start_progress = (task_start_date - schedule_start).total_seconds() / schedule_duration.total_seconds()
                task_finish_progress = (finish_date - schedule_start).total_seconds() / schedule_duration.total_seconds()

                # Convertir a frames
                task_start_frame = round(settings["start_frame"] + (task_start_progress * total_frames))
                task_finish_frame = round(settings["start_frame"] + (task_finish_progress * total_frames))

                # Validar que los frames estén en rango válido
                task_start_frame = max(settings["start_frame"], min(settings["end_frame"], task_start_frame))
                task_finish_frame = max(settings["start_frame"], min(settings["end_frame"], task_finish_frame))

                return {
                    "name": getattr(task, "Name", "Unnamed"),
                    "start_date": task_start_date,
                    "finish_date": finish_date,
                    "start_frame": task_start_frame,
                    "finish_frame": task_finish_frame,
                }
            except Exception as e:
                print(f"⚠️ Error calculating frames for task {getattr(task, 'Name', 'Unknown')}: {e}")
                return None
        def create_task_bar_data(tasks, vertical_increment, collection):
            # CORRECCIÓN: Usar fechas del cronograma activo, NO las de visualización
            schedule_start, schedule_finish = cls.get_schedule_date_range()

            if not (schedule_start and schedule_finish):
                # Fallback: si no hay fechas del cronograma, mostrar mensaje y abortar
                print("❌ No se pueden crear Task Bars: fechas del cronograma no disponibles")
                return None

            settings = {
                # CAMBIO CRÍTICO: Usar fechas del cronograma en lugar de visualización
                "viz_start": schedule_start,
                "viz_finish": schedule_finish,
                "start_frame": bpy.context.scene.frame_start,
                "end_frame": bpy.context.scene.frame_end,
            }

            print(f"🎯 Task Bars usando fechas del cronograma:")
            print(f"   Schedule Start: {schedule_start.strftime('%Y-%m-%d')}")
            print(f"   Schedule Finish: {schedule_finish.strftime('%Y-%m-%d')}")
            print(f"   Timeline: frames {settings['start_frame']} to {settings['end_frame']}")

            material_progress, material_full = get_animation_materials()
            empty = bpy.data.objects.new("collection_origin", None)
            link_collection(empty, collection)

            for task in tasks:
                task_data = process_task_data(task, settings)
                if task_data:
                    position_shift = task_data["start_frame"] * size_to_duration_ratio
                    bar_size = (task_data["finish_frame"] - task_data["start_frame"]) * size_to_duration_ratio

                    anim_props = cls.get_animation_props()
                    color_progress = anim_props.color_progress
                    bar = add_bar(
                        material=material_progress,
                        vertical_increment=vertical_increment,
                        collection=collection,
                        parent=empty,
                        task=task_data,
                        scale=True,
                        color=(color_progress[0], color_progress[1], color_progress[2], 1.0),
                        shift_x=position_shift,
                        name=task_data["name"] + "/Progress Bar",
                    )

                    color_full = anim_props.color_full
                    bar2 = add_bar(
                        material=material_full,
                        vertical_increment=vertical_increment,
                        parent=empty,
                        collection=collection,
                        task=task_data,
                        color=(color_full[0], color_full[1], color_full[2], 1.0),
                        shift_x=position_shift,
                        name=task_data["name"] + "/Full Bar",
                    )
                    bar2.color = (color_full[0], color_full[1], color_full[2], 1.0)

                    bar2.scale = (full_bar_thickness, bar_size, 1)
                    shift_object(bar2, y=((size + full_bar_thickness) / 2))

                    start_text = add_text(
                        task_data["start_date"].strftime("%d/%m/%y"),
                        0,
                        "RIGHT",
                        vertical_increment,
                        parent=empty,
                        collection=collection,
                    )
                    start_text.name = task_data["name"] + "/Start Date"
                    shift_object(start_text, x=position_shift - margin, y=-(size + full_bar_thickness))

                    task_text = add_text(
                        task_data["name"],
                        0,
                        "RIGHT",
                        vertical_increment,
                        parent=empty,
                        collection=collection,
                    )
                    task_text.name = task_data["name"] + "/Task Name"
                    shift_object(task_text, x=position_shift, y=0.2)

                    finish_text = add_text(
                        task_data["finish_date"].strftime("%d/%m/%y"),
                        bar_size,
                        "LEFT",
                        vertical_increment,
                        parent=empty,
                        collection=collection,
                    )
                    finish_text.name = task_data["name"] + "/Finish Date"
                    shift_object(finish_text, x=position_shift + margin, y=-(size + full_bar_thickness))

                vertical_increment += vertical_spacing

            return empty.select_set(True) if empty else None

        def set_material(name, r, g, b):
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            tool.Blender.get_material_node(material, "BSDF_PRINCIPLED").inputs[0].default_value = (r, g, b, 1.0)
            return material

        def get_animation_materials():
            if "color_progress" in bpy.data.materials:
                material_progress = bpy.data.materials["color_progress"]
            else:
                material_progress = set_material("color_progress", 0.0, 1.0, 0.0)
            if "color_full" in bpy.data.materials:
                material_full = bpy.data.materials["color_full"]
            else:
                material_full = set_material("color_full", 1.0, 0.0, 0.0)
            return material_progress, material_full

        def animate_scale(bar, task):
            scale = (1, size_to_duration_ratio, 1)
            bar.scale = scale
            bar.keyframe_insert(data_path="scale", frame=task["start_frame"])
            scale2 = (1, (task["finish_frame"] - task["start_frame"]) * size_to_duration_ratio, 1)
            bar.scale = scale2
            bar.keyframe_insert(data_path="scale", frame=task["finish_frame"])

        def animate_color(bar, task, color):
            bar.keyframe_insert(data_path="color", frame=task["start_frame"])
            bar.color = color
            bar.keyframe_insert(data_path="color", frame=task["start_frame"] + 1)
            bar.color = color

        def place_bar(bar, vertical_increment):
            for vertex in bar.data.vertices:
                vertex.co[1] += 0.5
            bar.rotation_euler[2] = -1.5708
            shift_object(bar, y=-vertical_increment)

        def shift_object(obj, x=0.0, y=0.0, z=0.0):
            vec = mathutils.Vector((x, y, z))
            inv = obj.matrix_world.copy()
            inv.invert()
            vec_rot = vec @ inv
            obj.location = obj.location + vec_rot

        def link_collection(obj, collection):
            if collection:
                collection.objects.link(obj)
                if obj.name in bpy.context.scene.collection.objects.keys():
                    bpy.context.scene.collection.objects.unlink(obj)
            return obj

        def create_plane(material, collection, vertical_increment):
            x = 0.5
            y = 0.5
            vert = [(-x, -y, 0.0), (x, -y, 0.0), (-x, y, 0.0), (x, y, 0.0)]
            fac = [(0, 1, 3, 2)]
            mesh = bpy.data.meshes.new("PL")
            mesh.from_pydata(vert, [], fac)
            obj = bpy.data.objects.new("PL", mesh)
            obj.data.materials.append(material)
            place_bar(obj, vertical_increment)
            link_collection(obj, collection)
            return obj

        def add_text(text, x_position, align, vertical_increment, parent=None, collection=None):
            data = bpy.data.curves.new(type="FONT", name="Timeline")
            data.align_x = align
            data.align_y = "CENTER"

            data.body = text
            obj = bpy.data.objects.new(name="Unnamed", object_data=data)
            link_collection(obj, collection)
            shift_object(obj, x=x_position, y=-(vertical_increment - 1))
            if parent:
                obj.parent = parent
            return obj

        def add_bar(
            material,
            vertical_increment,
            parent=None,
            collection=None,
            task=None,
            color=False,
            scale=False,
            shift_x=None,
            name=None,
        ):
            plane = create_plane(material, collection, vertical_increment)
            if parent:
                plane.parent = parent
            if color:
                animate_color(plane, task, color)
            if scale:
                animate_scale(plane, task)
            if shift_x:
                shift_object(plane, x=shift_x)
            if name:
                plane.name = name
            return plane

        if "Bar Visual" in bpy.data.collections:
            collection = bpy.data.collections["Bar Visual"]
            for obj in collection.objects:
                bpy.data.objects.remove(obj)

        else:
            collection = bpy.data.collections.new("Bar Visual")
            bpy.context.scene.collection.children.link(collection)

        if tasks:
            create_task_bar_data(tasks, vertical_increment, collection)

    @classmethod
    def has_animation_colors(cls):
        return bpy.context.scene.BIMAnimationProperties.task_output_colors

    @classmethod
    def load_default_animation_color_scheme(cls):
        def _to_rgba(col):
            try:
                if isinstance(col, (list, tuple)):
                    if len(col) >= 4:
                        return (float(col[0]), float(col[1]), float(col[2]), float(col[3]))
                    if len(col) == 3:
                        return (float(col[0]), float(col[1]), float(col[2]), 1.0)
            except Exception:
                pass
            return (1.0, 0.0, 0.0, 1.0)

        groups = {
            "CREATION": {"PredefinedType": ["CONSTRUCTION", "INSTALLATION"], "Color": (0.0, 1.0, 0.0)},
            "OPERATION": {"PredefinedType": ["ATTENDANCE", "MAINTENANCE", "OPERATION", "RENOVATION"], "Color": (0.0, 0.0, 1.0)},
            "MOVEMENT_TO": {"PredefinedType": ["LOGISTIC", "MOVE"], "Color": (1.0, 1.0, 0.0)},
            "DESTRUCTION": {"PredefinedType": ["DEMOLITION", "DISMANTLE", "DISPOSAL", "REMOVAL"], "Color": (1.0, 0.0, 0.0)},
            "MOVEMENT_FROM": {"PredefinedType": ["LOGISTIC", "MOVE"], "Color": (1.0, 0.5, 0.0)},
            "USERDEFINED": {"PredefinedType": ["USERDEFINED", "NOTDEFINED"], "Color": (0.2, 0.2, 0.2)},
        }

        props = cls.get_animation_props()
        props.task_output_colors.clear()
        props.task_input_colors.clear()

        for group, data in groups.items():
            for predefined_type in data["PredefinedType"]:
                if group in ["CREATION", "OPERATION", "MOVEMENT_TO"]:
                    item = props.task_output_colors.add()
                elif group in ["MOVEMENT_FROM"]:
                    item = props.task_input_colors.add()
                elif group in ["USERDEFINED", "DESTRUCTION"]:
                    item = props.task_input_colors.add()
                    item2 = props.task_output_colors.add()
                    item2.name = predefined_type
                    item2.color = _to_rgba(data["Color"])
                item.name = predefined_type
                item.color = _to_rgba(data["Color"])

    @classmethod

    def get_start_date(cls) -> Union[datetime, None]:
        """Devuelve la fecha de inicio configurada (visualisation_start) o None.
        Parseo robusto: ISO-8601 primero (YYYY-MM-DD), luego dateutil con yearfirst=True.
        """
        props = cls.get_work_schedule_props()
        s = getattr(props, "visualisation_start", None)
        if not s or s == "-":
            return None
        try:
            from datetime import datetime as _dt
            if isinstance(s, str):
                try:
                    if "T" in s or " " in s:
                        s2 = s.replace(" ", "T")
                        dt = _dt.fromisoformat(s2[:19])
                    else:
                        dt = _dt.fromisoformat(s[:10])
                    return dt.replace(microsecond=0)
                except Exception:
                    pass
            if isinstance(s, (_dt, )):
                return s.replace(microsecond=0)
        except Exception:
            pass
        try:
            from dateutil import parser
            dt = parser.parse(str(s), yearfirst=True, dayfirst=False, fuzzy=True)
            return dt.replace(microsecond=0)
        except Exception:
            try:
                dt = parser.parse(str(s), yearfirst=True, dayfirst=True, fuzzy=True)
                return dt.replace(microsecond=0)
            except Exception as e:
                print(f"❌ Error parseando visualisation_start: {s} -> {e}")
                return None

    @classmethod


    def get_finish_date(cls) -> Union[datetime, None]:
        """Devuelve la fecha de fin configurada (visualisation_finish) o None.
        Parseo robusto: ISO-8601 primero, luego dateutil con yearfirst=True.
        """
        props = cls.get_work_schedule_props()
        s = getattr(props, "visualisation_finish", None)
        if not s or s == "-":
            return None
        try:
            from datetime import datetime as _dt
            if isinstance(s, str):
                try:
                    if "T" in s or " " in s:
                        s2 = s.replace(" ", "T")
                        dt = _dt.fromisoformat(s2[:19])
                    else:
                        dt = _dt.fromisoformat(s[:10])
                    return dt.replace(microsecond=0)
                except Exception:
                    pass
            if isinstance(s, (_dt, )):
                return s.replace(microsecond=0)
        except Exception:
            pass
        try:
            from dateutil import parser
            dt = parser.parse(str(s), yearfirst=True, dayfirst=False, fuzzy=True)
            return dt.replace(microsecond=0)
        except Exception:
            try:
                dt = parser.parse(str(s), yearfirst=True, dayfirst=True, fuzzy=True)
                return dt.replace(microsecond=0)
            except Exception as e:
                print(f"❌ Error parseando visualisation_finish: {s} -> {e}")
                return None


    @classmethod
    def get_visualization_date_range(cls):
        """
        Obtiene el rango de fechas de visualización configurado en la UI.

        Returns:
        tuple: (viz_start: datetime, viz_finish: datetime) o (None, None) si no están configuradas
        """
        try:
            props = cls.get_work_schedule_props()
            viz_start = cls.get_start_date()  # Ya existe esta función
            viz_finish = cls.get_finish_date()  # Ya existe esta función

            return viz_start, viz_finish
        except Exception as e:
            print(f"⚠️ Error obteniendo rango de visualización: {e}")
            return None, None

    @classmethod
    def process_construction_state(cls, work_schedule: ifcopenshell.entity_instance, date: datetime, viz_start: datetime = None, viz_finish: datetime = None) -> dict[str, Any]:
        """
        CORRECCIÓN: Procesa estados considerando el rango de visualización configurado.

        Args:
            work_schedule: Cronograma de trabajo
            date: Fecha actual del snapshot
            viz_start: Fecha de inicio de visualización (opcional)
            viz_finish: Fecha de fin de visualización (opcional)
        """
        cls.to_build = set()
        cls.in_construction = set()
        cls.completed = set()
        cls.to_demolish = set()
        cls.in_demolition = set()
        cls.demolished = set()

        for rel in work_schedule.Controls or []:
            for related_object in rel.RelatedObjects:
                if related_object.is_a("IfcTask"):
                    cls.process_task_status(related_object, date, viz_start, viz_finish)

        return {
            "TO_BUILD": cls.to_build,
            "IN_CONSTRUCTION": cls.in_construction,
            "COMPLETED": cls.completed,
            "TO_DEMOLISH": cls.to_demolish,
            "IN_DEMOLITION": cls.in_demolition,
            "DEMOLISHED": cls.demolished,
        }

    @classmethod
    def process_task_status(cls, task: ifcopenshell.entity_instance, date: datetime, viz_start: datetime = None, viz_finish: datetime = None) -> None:
        """
        CORRECCIÓN: Procesa el estado de una tarea considerando el rango de visualización.

        Lógica corregida:
        1. Tareas que terminan antes de viz_start: outputs completados, inputs demolidos
        2. Tareas que empiezan después de viz_finish: NO aparecen (se omiten)
        3. Tareas dentro del rango: lógica normal basada en la fecha actual
        """
        # Procesar tareas anidadas recursivamente
        for rel in task.IsNestedBy or []:
            [cls.process_task_status(related_object, date, viz_start, viz_finish) for related_object in rel.RelatedObjects]

        start = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
        finish = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)

        if not start or not finish:
            return

        outputs = ifcopenshell.util.sequence.get_task_outputs(task) or []
        inputs = cls.get_task_inputs(task) or []

        # NUEVA LÓGICA: Considerar rango de visualización

        # 1. Tarea empieza después del fin de visualización -> NO MOSTRAR
        if viz_finish and start > viz_finish:
            # Estas tareas no deben aparecer en absoluto
            return

        # 2. Tarea termina antes del inicio de visualización -> MOSTRAR COMO COMPLETADA
        if viz_start and finish < viz_start:
            # Outputs completados (visibles), inputs demolidos (ocultos)
            [cls.completed.add(tool.Ifc.get_object(output)) for output in outputs]
            [cls.demolished.add(tool.Ifc.get_object(input)) for input in inputs]
            return

        # 3. Tarea dentro del rango de visualización -> LÓGICA NORMAL
        # (También incluye tareas que se extienden parcialmente fuera del rango)

        if date < start:
            # Antes del inicio: outputs ocultos, inputs visibles
            [cls.to_build.add(tool.Ifc.get_object(output)) for output in outputs]
            [cls.to_demolish.add(tool.Ifc.get_object(input)) for input in inputs]
        elif date <= finish:
            # Durante la ejecución
            [cls.in_construction.add(tool.Ifc.get_object(output)) for output in outputs]
            [cls.in_demolition.add(tool.Ifc.get_object(input)) for input in inputs]
        else:
            # Después de finalizar: outputs permanecen visibles, inputs desaparecen
            [cls.completed.add(tool.Ifc.get_object(output)) for output in outputs]
            [cls.demolished.add(tool.Ifc.get_object(input)) for input in inputs]

    @classmethod
    def show_snapshot(cls, product_states):
        """CORRECCIÓN: Respetar consider_start en snapshots"""

        # 1. Limpiar keyframes previos y guardar propiedades originales
        original_properties = {}
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                original_properties[obj.name] = {
                    "color": list(obj.color),
                    "hide": obj.hide_get()
                }
            if obj.animation_data:
                obj.animation_data_clear()

        # 2. Determinar el grupo de perfiles correcto DESDE EL ANIMATION STACK
        anim_props = cls.get_animation_props()
        active_group_name = None

        # Iterar sobre el stack de animación para encontrar el primer grupo habilitado
        for item in anim_props.animation_group_stack:
            if item.enabled and item.group:
                active_group_name = item.group
                print(f"✅ Snapshot: Usando el grupo '{active_group_name}' desde el Animation Stack.")
                break # Usar el primero que encuentre (el de mayor prioridad)

        # Si el stack está vacío o no hay grupos habilitados, usar DEFAULT como fallback
        if not active_group_name:
            active_group_name = "DEFAULT"
            print(f"⚠️ Snapshot: Animation Stack vacío. Usando grupo 'DEFAULT' como fallback.")

        # Sincronizar el grupo de la UI si coincide con el que vamos a usar, para capturar cambios no guardados.
        if active_group_name == getattr(anim_props, "profile_groups", None):
            cls.sync_active_group_to_json()

        # 3. Resetear todos los objetos IFC (ocultar por defecto)
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and tool.Ifc.get_entity(obj):
                obj.hide_viewport = True
                obj.hide_render = True
                obj.color = (0.5, 0.5, 0.5, 0.2)

        # 4. Mapeo de estados a perfiles del grupo activo
        def get_task_profile(task_type):
            """Obtiene el perfil correcto del grupo activo para el tipo de tarea."""
            # Buscar perfil por nombre específico (ej: "CONSTRUCTION")
            profile = cls.load_profile_from_group(active_group_name, task_type)
            if profile:
                return profile

            # Si no, buscar el perfil "NOTDEFINED" dentro del mismo grupo
            profile = cls.load_profile_from_group(active_group_name, "NOTDEFINED")
            if profile:
                return profile

            # Como último recurso, crear un perfil genérico
            return cls.create_generic_profile(task_type)

        # 5. Configuración de estados
        state_configs = {
            "TO_BUILD": {"state": "start", "default_type": "CONSTRUCTION", "visibility": "hidden"},
            "IN_CONSTRUCTION": {"state": "in_progress", "default_type": "CONSTRUCTION", "visibility": "visible"},
            "COMPLETED": {"state": "end", "default_type": "CONSTRUCTION", "visibility": "visible"},
            "TO_DEMOLISH": {"state": "start", "default_type": "DEMOLITION", "visibility": "visible"},
            "IN_DEMOLITION": {"state": "in_progress", "default_type": "DEMOLITION", "visibility": "visible"},
            "DEMOLISHED": {"state": "end", "default_type": "DEMOLITION", "visibility": "hidden"}
        }

        task_type_cache = {}
        applied_count = 0

        # 6. Aplicar estados visuales
        for state_name, products in product_states.items():
            if not products:
                continue

            config = state_configs.get(state_name)
            if not config:
                continue

            for obj in products:
                if not obj: continue

                element = tool.Ifc.get_entity(obj)
                if not element: continue

                task = cls.get_task_for_product(element)
                task_type = (task.PredefinedType if task else None) or config["default_type"]

                profile = get_task_profile(task_type)
                original_color = original_properties.get(obj.name, {}).get("color", [1,1,1,1])

                # NUEVA LÓGICA: Si consider_start está activo, usar siempre apariencia de start
                if getattr(profile, 'consider_start', False):
                    # Forzar estado "start" independientemente del estado real del cronograma
                    obj.hide_viewport = False
                    obj.hide_render = False

                    use_original = getattr(profile, 'use_start_original_color', False)
                    color = original_color if use_original else list(profile.start_color)
                    transparency = getattr(profile, 'start_transparency', 0.0)

                    obj.color = (color[0], color[1], color[2], 1.0 - transparency)
                    applied_count += 1
                    print(f"✅ Snapshot: {obj.name} usa consider_start=True, aplicando apariencia de start")
                    continue

                # Aplicar visibilidad normal solo si consider_start está desactivado
                if config["visibility"] == "hidden":
                    obj.hide_viewport = True
                    obj.hide_render = True
                    applied_count += 1
                    continue
                else:
                    obj.hide_viewport = False
                    obj.hide_render = False

                # Aplicar color y transparencia
                state_key = config["state"]
                color = [1,1,1,1]
                transparency = 0.0

                if state_key == "start":
                    use_original = getattr(profile, 'use_start_original_color', False)
                    color = original_color if use_original else list(profile.start_color)
                    transparency = getattr(profile, 'start_transparency', 0.0)
                elif state_key == "in_progress":
                    use_original = getattr(profile, 'use_active_original_color', False)
                    color = original_color if use_original else list(profile.in_progress_color)
                    transparency = (getattr(profile, 'active_start_transparency', 0.0) + getattr(profile, 'active_finish_transparency', 0.0)) / 2.0
                elif state_key == "end":
                    use_original = getattr(profile, 'use_end_original_color', True)
                    color = original_color if use_original else list(profile.end_color)
                    transparency = getattr(profile, 'end_transparency', 0.0)

                obj.color = (color[0], color[1], color[2], 1.0 - transparency)
                applied_count += 1

        # Al final, asegurar que objetos no procesados permanezcan ocultos
        processed_objects = set()
        for state_name, products in product_states.items():
            for obj in products:
                if obj:
                    processed_objects.add(obj)

        # Asegurar que objetos no procesados permanezcan ocultos
        for obj in bpy.data.objects:
            if (obj.type == 'MESH' and
                tool.Ifc.get_entity(obj) and
                obj not in processed_objects):
                obj.hide_viewport = True
                obj.hide_render = True

        # 7. Configurar la vista 3D
        cls.set_object_shading()
        print(f"✅ Snapshot aplicado a {applied_count} objetos usando el grupo '{active_group_name}'")

    @classmethod
    def get_task_for_product(cls, product):
        """Obtiene la tarea asociada a un producto IFC."""
        element = tool.Ifc.get_entity(product) if hasattr(product, 'name') else product
        if not element:
            return None

        # Buscar en outputs
        for rel in element.ReferencedBy or []:
            if rel.is_a("IfcRelAssignsToProduct"):
                for task in rel.RelatedObjects:
                    if task.is_a("IfcTask"):
                        return task

        # Buscar en inputs
        for rel in element.HasAssignments or []:
            if rel.is_a("IfcRelAssignsToProcess"):
                task = rel.RelatingProcess
                if task.is_a("IfcTask"):
                    return task

        return None
    @classmethod
    def set_object_shading(cls):
            area = tool.Blender.get_view3d_area()
            if area:
                # Use area.spaces.active for stability in newer Blender versions
                space = area.spaces.active
                if space and space.type == 'VIEW_3D':
                    space.shading.color_type = "OBJECT"

    @classmethod
    def get_animation_settings(cls):
        """
        CORRECCIÓN: Asegurar que use las fechas de visualización configuradas,
        no las fechas derivadas de las tareas.
        """
        def calculate_total_frames(fps):
            if props.speed_types == "FRAME_SPEED":
                return calculate_using_frames(
                    start,
                    finish,
                    props.speed_animation_frames,
                    ifcopenshell.util.date.parse_duration(props.speed_real_duration),
                )
            elif props.speed_types == "DURATION_SPEED":
                animation_duration = ifcopenshell.util.date.parse_duration(props.speed_animation_duration)
                real_duration = ifcopenshell.util.date.parse_duration(props.speed_real_duration)
                return calculate_using_duration(
                    start,
                    finish,
                    fps,
                    animation_duration,
                    real_duration,
                )
            elif props.speed_types == "MULTIPLIER_SPEED":
                return calculate_using_multiplier(
                    start,
                    finish,
                    1,
                    props.speed_multiplier,
                )

        def calculate_using_multiplier(start, finish, fps, multiplier):
            animation_time = (finish - start) / multiplier
            return animation_time.total_seconds() * fps

        def calculate_using_duration(start, finish, fps, animation_duration, real_duration):
            return calculate_using_multiplier(start, finish, fps, real_duration / animation_duration)

        def calculate_using_frames(start, finish, animation_frames, real_duration):
            return ((finish - start) / real_duration) * animation_frames
        props = cls.get_work_schedule_props()
        # Obtener fechas de visualización: primero UI, si faltan, inferir del cronograma activo
        viz_start_prop = getattr(props, "visualisation_start", None)
        viz_finish_prop = getattr(props, "visualisation_finish", None)

        inferred_start = None
        inferred_finish = None
        if not (viz_start_prop and viz_finish_prop):
            try:
                ws = cls.get_active_work_schedule()
                if ws:
                    inferred_start, inferred_finish = cls.guess_date_range(ws)
            except Exception:
                inferred_start, inferred_finish = (None, None)

        def _to_dt(v):
            try:
                from datetime import datetime as _dt, date as _d
                if isinstance(v, _dt):
                    return v.replace(microsecond=0)
                if isinstance(v, _d):
                    return _dt(v.year, v.month, v.day)
                s = str(v)
                try:
                    if "T" in s or " " in s:
                        s2 = s.replace(" ", "T")
                        return _dt.fromisoformat(s2[:19])
                    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                        return _dt.fromisoformat(s[:10])
                except Exception:
                    pass
                from dateutil import parser as _p
                return _p.parse(s, yearfirst=True, dayfirst=False, fuzzy=True)
            except Exception:
                try:
                    from dateutil import parser as _p
                    return _p.parse(str(v), yearfirst=True, dayfirst=True, fuzzy=True)
                except Exception:
                    return None

        if viz_start_prop and viz_finish_prop:
            start = cls.get_start_date()
            finish = cls.get_finish_date()
        else:
            start = _to_dt(inferred_start)
            finish = _to_dt(inferred_finish)
            try:
                if start and finish:
                    props.visualisation_start = ifcopenshell.util.date.canonicalise_time(start)
                    props.visualisation_finish = ifcopenshell.util.date.canonicalise_time(finish)
            except Exception:
                pass

        if not start or not finish:
            print("❌ No se pudieron determinar fechas de visualización (UI ni inferidas)")
            return None

        try:
            start = start.replace(microsecond=0)
            finish = finish.replace(microsecond=0)
        except Exception:
            pass

        if finish <= start:
            try:
                from datetime import timedelta as _td
                if finish == start:
                    finish = start + _td(days=1)
                else:
                    print(f"❌ Error: Fecha de fin ({finish}) debe ser posterior a fecha de inicio ({start})")
                    return None
            except Exception:
                print(f"❌ Error ajustando rango de fechas: start={start}, finish={finish}")
                return None


        duration = finish - start
        # Usar frame_start de la escena si existe; por defecto 1
        try:
            start_frame = int(getattr(bpy.context.scene, 'frame_start', 1) or 1)
        except Exception:
            start_frame = 1

        # Calcular frames totales basados en la configuración de velocidad
        try:
            fps = int(getattr(bpy.context.scene.render, 'fps', 24) or 24)
        except Exception:
            fps = 24
        total_frames = int(round(calculate_total_frames(fps)))

        print(f"📅 Animation Settings:")
        try:
            print(f"   Start Date: {start.strftime('%Y-%m-%d')}")
            print(f"   Finish Date: {finish.strftime('%Y-%m-%d')}")
        except Exception:
            print(f"   Start Date: {start}")
            print(f"   Finish Date: {finish}")
        print(f"   Duration: {duration.days} days")
        print(f"   Start Frame: {start_frame}")
        print(f"   Total Frames: {total_frames}")

        return {
            "start": start,
            "finish": finish,
            "duration": duration,
            "start_frame": start_frame,
            "total_frames": total_frames,
            # NUEVO: Agregar fechas del cronograma completo para referencia
            "schedule_start": None,
            "schedule_finish": None,
        }

    @classmethod
    def get_animation_product_frames(cls, work_schedule: ifcopenshell.entity_instance, settings: dict[str, Any]):

            def add_product_frame(product_id, type, product_start, product_finish, relationship):
                product_frames.setdefault(product_id, []).append(
                    {
                        "type": type,
                        "relationship": relationship,
                        "STARTED": round(
                            settings["start_frame"]
                            + (((product_start - settings["start"]) / settings["duration"]) * settings["total_frames"])
                        ),
                        "COMPLETED": round(
                            settings["start_frame"]
                            + (((product_finish - settings["start"]) / settings["duration"]) * settings["total_frames"])
                        ),
                    }
                )

            product_frames = {}
            for root_task in ifcopenshell.util.sequence.get_root_tasks(work_schedule):
                preprocess_task(root_task)
            return product_frames
    @classmethod
    def create_default_profile_group(cls):
            """
            Crea automáticamente el grupo DEFAULT con perfiles para cada PredefinedType.
            Este grupo se usa cuando el usuario no ha configurado ningún perfil.
            """
            import json
            scene = bpy.context.scene
            key = "BIM_AppearanceProfileSets"
            raw = scene.get(key, "{}")
            try:
                data = json.loads(raw) if isinstance(raw, str) else {}
            except Exception:
                data = {}
            if "DEFAULT" not in data:
                default_profiles = {
                    "CONSTRUCTION": {"start": [1, 1, 1, 0], "active": [0, 1, 0, 1], "end": [0.3, 1, 0.3, 1]},
                    "INSTALLATION": {"start": [1, 1, 1, 0], "active": [0, 0.8, 0.5, 1], "end": [0.3, 0.8, 0.5, 1]},
                    "DEMOLITION": {"start": [1, 1, 1, 1], "active": [1, 0, 0, 1], "end": [0, 0, 0, 0], "hide_at_end": True},
                    "REMOVAL": {"start": [1, 1, 1, 1], "active": [1, 0.3, 0, 1], "end": [0, 0, 0, 0], "hide_at_end": True},
                    "DISPOSAL": {"start": [1, 1, 1, 1], "active": [0.8, 0, 0.2, 1], "end": [0, 0, 0, 0], "hide_at_end": True},
                    "DISMANTLE": {"start": [1, 1, 1, 1], "active": [1, 0.5, 0, 1], "end": [0, 0, 0, 0], "hide_at_end": True},
                    "OPERATION": {"start": [1, 1, 1, 1], "active": [0, 0.5, 1, 1], "end": [1, 1, 1, 1]},
                    "MAINTENANCE": {"start": [1, 1, 1, 1], "active": [0.3, 0.6, 1, 1], "end": [1, 1, 1, 1]},
                    "ATTENDANCE": {"start": [1, 1, 1, 1], "active": [0.5, 0.5, 1, 1], "end": [1, 1, 1, 1]},
                    "RENOVATION": {"start": [1, 1, 1, 1], "active": [0.5, 0, 1, 1], "end": [0.9, 0.9, 0.9, 1]}
                }
                profiles = []
                for name, colors in default_profiles.items():
                    disappears = name in ["DEMOLITION", "REMOVAL", "DISPOSAL", "DISMANTLE"]
                    profiles.append({
                        "name": name,
                        "consider_start": True,
                        "consider_active": True,
                        "consider_end": True,
                        "start_color": colors["start"],
                        "in_progress_color": colors["active"],
                        "end_color": colors["end"],
                        "use_start_original_color": False,
                        "use_active_original_color": False,
                        "use_end_original_color": not disappears,
                        "start_transparency": 0.0,
                        "active_start_transparency": 0.0,
                        "active_finish_transparency": 0.0,
                        "active_transparency_interpol": 1.0,
                        "end_transparency": 0.0
                    })
                data["DEFAULT"] = {"profiles": profiles}
                scene[key] = json.dumps(data)

    # ==================================================================
    # === 1. FUNCIÓN CORREGIDA (PREPARACIÓN DE DATOS) ==================
    # ==================================================================
    @classmethod
    def get_animation_product_frames_enhanced(cls, work_schedule: ifcopenshell.entity_instance, settings: dict[str, Any]):
        animation_start = int(settings["start_frame"])
        animation_end = int(settings["start_frame"] + settings["total_frames"])
        viz_start = settings["start"]
        viz_finish = settings["finish"]
        viz_duration = settings["duration"]
        product_frames: dict[int, list] = {}

        def add_product_frame_enhanced(product_id, task, start_date, finish_date, start_frame, finish_frame, relationship):
            if finish_date < viz_start:
                states = {
                    "before_start": (animation_start, animation_start - 1),
                    "active": (animation_start, animation_start - 1),
                    "after_end": (animation_start, animation_end),
                }
            elif start_date > viz_finish:
                return
            else:
                s_vis = max(animation_start, int(start_frame))
                f_vis = min(animation_end, int(finish_frame))
                if f_vis < s_vis:
                    s_vis = max(animation_start, min(animation_end, s_vis))
                    f_vis = s_vis
                before_end = s_vis - 1
                after_start = f_vis + 1
                states = {
                    "before_start": (animation_start, before_end) if before_end >= animation_start else (animation_start, animation_start - 1),
                    "active": (s_vis, f_vis),
                    "after_end": (after_start if after_start <= animation_end else animation_end + 1, animation_end),
                }

            product_frames.setdefault(product_id, []).append({
                "task": task, "task_id": task.id(),
                "type": getattr(task, "PredefinedType", "NOTDEFINED"),
                "relationship": relationship,
                "start_date": start_date, "finish_date": finish_date,
                "STARTED": int(start_frame), "COMPLETED": int(finish_frame),
                "start_frame": max(animation_start, int(start_frame)),
                "finish_frame": min(animation_end, int(finish_frame)),
                "states": states,
            })

        def add_product_frame_full_range(product_id, task, relationship):
            states = { "active": (animation_start, animation_end) }
            product_frames.setdefault(product_id, []).append({
                "task": task, "task_id": task.id(),
                "type": getattr(task, "PredefinedType", "NOTDEFINED"),
                "relationship": relationship,
                "start_date": viz_start, "finish_date": viz_finish,
                "STARTED": animation_start, "COMPLETED": animation_end,
                "start_frame": animation_start, "finish_frame": animation_end,
                "states": states,
                "consider_start_active": True,
            })
            print(f"🔒 Product {product_id}: Frame de rango completo (ignora fechas) creado.")

        def preprocess_task(task):
            for subtask in ifcopenshell.util.sequence.get_nested_tasks(task):
                preprocess_task(subtask)

            task_start = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
            task_finish = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)
            if not task_start or not task_finish:
                return

            # === CAMBIO CLAVE ===
            # Obtener el perfil completo para verificar la combinación de estados, no solo 'consider_start'.
            profile = cls._get_best_profile_for_task(task, cls.get_animation_props())
            is_priority_mode = (
                getattr(profile, 'consider_start', False) and
                not getattr(profile, 'consider_active', True) and
                not getattr(profile, 'consider_end', True)
            )

            # Si es modo prioritario, IGNORAR FECHAS y usar el rango completo.
            if is_priority_mode:
                print(f"🔒 Tarea '{task.Name}' en modo prioritario. Ignorando fechas.")
                for output in ifcopenshell.util.sequence.get_task_outputs(task):
                    add_product_frame_full_range(output.id(), task, "output")
                for input_prod in cls.get_task_inputs(task):
                    add_product_frame_full_range(input_prod.id(), task, "input")
                return

            # Si NO es modo prioritario, usar las fechas de la tarea para calcular los fotogramas.
            if task_start > viz_finish:
                return

            if viz_duration.total_seconds() > 0:
                start_progress = (task_start - viz_start).total_seconds() / viz_duration.total_seconds()
                finish_progress = (task_finish - viz_start).total_seconds() / viz_duration.total_seconds()
            else:
                start_progress, finish_progress = 0.0, 1.0

            sf = int(round(settings["start_frame"] + (start_progress * settings["total_frames"])))
            ff = int(round(settings["start_frame"] + (finish_progress * settings["total_frames"])))

            for output in ifcopenshell.util.sequence.get_task_outputs(task):
                add_product_frame_enhanced(output.id(), task, task_start, task_finish, sf, ff, "output")
            for input_prod in cls.get_task_inputs(task):
                add_product_frame_enhanced(input_prod.id(), task, task_start, task_finish, sf, ff, "input")

        for root_task in ifcopenshell.util.sequence.get_root_tasks(work_schedule):
            preprocess_task(root_task)

        return product_frames

    @classmethod
    def get_assigned_profile_for_task(cls, task, animation_props, active_group_name=None):
        """Obtiene el perfil para una tarea DADO un grupo activo específico."""
        # Resolver grupo activo si no fue provisto
        if not active_group_name:
            try:
                ag = None
                # Preferir el Animation Stack (primer habilitado)
                for it in getattr(animation_props, 'animation_group_stack', []):
                    if getattr(it, 'enabled', False) and getattr(it, 'group', None):
                        ag = it.group
                        break
                if not ag:
                    ag = getattr(animation_props, 'profile_groups', None)
                active_group_name = ag or 'DEFAULT'
            except Exception:
                active_group_name = 'DEFAULT'

        task_tree_props = cls.get_task_tree_props()
        task_item = None
        for item in task_tree_props.tasks:
            if item.ifc_definition_id == task.id():
                task_item = item
                break

        task_predefined_type = getattr(task, "PredefinedType", None) or "NOTDEFINED"

        # 1) Asignación específica por grupo en la tarea
        if task_item and hasattr(task_item, 'profile_group_choices'):
            for choice in task_item.profile_group_choices:
                if getattr(choice, "group_name", None) == active_group_name and getattr(choice, "selected_profile", None):
                    profile = cls.load_profile_from_group(active_group_name, choice.selected_profile)
                    if profile:
                        return profile

        # 2) PredefinedType en grupo activo
        profile = cls.load_profile_from_group(active_group_name, task_predefined_type)
        if profile:
            return profile

        # 3) PredefinedType en DEFAULT
        if active_group_name != "DEFAULT":
            profile = cls.load_profile_from_group("DEFAULT", task_predefined_type)
            if profile:
                return profile

        # 4) Genérico
        return cls.create_generic_profile(task_predefined_type)

    @classmethod
    def load_profile_from_group(cls, group_name, profile_name):
        import bpy, json
        scene = bpy.context.scene
        raw = scene.get("BIM_AppearanceProfileSets", "{}")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            data = {}
        group_data = data.get(group_name, {})
        for prof_data in group_data.get("profiles", []):
            if prof_data.get("name") == profile_name:
                return type('AppearanceProfile', (object,), {
                    'name': prof_data.get("name", ""),
                    'consider_start': prof_data.get("consider_start", True),
                    'consider_active': prof_data.get("consider_active", True),
                    'consider_end': prof_data.get("consider_end", True),
                    'start_color': prof_data.get("start_color", [1,1,1,1]),
                    'in_progress_color': prof_data.get("in_progress_color", [1,1,0,1]),
                    'end_color': prof_data.get("end_color", [0,1,0,1]),
                    'use_start_original_color': prof_data.get("use_start_original_color", False),
                    'use_active_original_color': prof_data.get("use_active_original_color", False),
                    'use_end_original_color': prof_data.get("use_end_original_color", True),
                    'start_transparency': prof_data.get("start_transparency", 0.0),
                    'active_start_transparency': prof_data.get("active_start_transparency", 0.0),
                    'active_finish_transparency': prof_data.get("active_finish_transparency", 0.0),
                    'active_transparency_interpol': prof_data.get("active_transparency_interpol", 1.0),
                    'end_transparency': prof_data.get("end_transparency", 0.0),
                    'hide_at_end': bool(prof_data.get("hide_at_end", prof_data.get("name") in {"DEMOLITION","REMOVAL","DISPOSAL","DISMANTLE"})),
                })()
        return None

    @classmethod
    def sync_active_group_to_json(cls):
        """Sincroniza los perfiles del grupo activo de la UI al JSON de la escena"""
        import bpy, json
        scene = bpy.context.scene
        anim_props = cls.get_animation_props()
        active_group = getattr(anim_props, "profile_groups", None)
        if not active_group:
            return
        raw = scene.get("BIM_AppearanceProfileSets", "{}")
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            data = {}
        profiles_data = []
        for profile in getattr(anim_props, "profiles", []):
            try:
                profiles_data.append({
                    "name": profile.name,
                    "consider_start": bool(getattr(profile, "consider_start", True)),
                    "consider_active": bool(getattr(profile, "consider_active", True)),
                    "consider_end": bool(getattr(profile, "consider_end", True)),
                    "start_color": list(getattr(profile, "start_color", [1,1,1,1])),
                    "in_progress_color": list(getattr(profile, "in_progress_color", [1,1,0,1])),
                    "end_color": list(getattr(profile, "end_color", [0,1,0,1])),
                    "use_start_original_color": bool(getattr(profile, "use_start_original_color", False)),
                    "use_active_original_color": bool(getattr(profile, "use_active_original_color", False)),
                    "use_end_original_color": bool(getattr(profile, "use_end_original_color", True)),
                    "start_transparency": float(getattr(profile, "start_transparency", 0.0)),
                    "active_start_transparency": float(getattr(profile, "active_start_transparency", 0.0)),
                    "active_finish_transparency": float(getattr(profile, "active_finish_transparency", 0.0)),
                    "active_transparency_interpol": float(getattr(profile, "active_transparency_interpol", 1.0)),
                    "end_transparency": float(getattr(profile, "end_transparency", 0.0)),
                    "hide_at_end": bool(getattr(profile, "hide_at_end", getattr(profile, "name", "") in {"DEMOLITION","REMOVAL","DISPOSAL","DISMANTLE"})),
                })
            except Exception:
                pass
        data[active_group] = {"profiles": profiles_data}
        scene["BIM_AppearanceProfileSets"] = json.dumps(data)
    @classmethod
    def animate_objects_with_profiles(cls, settings, product_frames):
        animation_props = cls.get_animation_props()
        # Lógica del grupo activo (stack → DEFAULT)
        active_group_name = None
        for item in getattr(animation_props, "animation_group_stack", []):
            if getattr(item, "enabled", False) and getattr(item, "group", None):
                active_group_name = item.group
                break
        if not active_group_name:
            active_group_name = "DEFAULT"
        print(f"🎬 INICIANDO ANIMACIÓN: Usando el grupo de perfiles '{active_group_name}'")

        original_colors = {}
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                original_colors[obj.name] = list(obj.color)

        for obj in bpy.data.objects:
            element = tool.Ifc.get_entity(obj)
            if not element:
                continue

            if element.is_a("IfcSpace"):
                cls.hide_object(obj)
                continue

            original_color = original_colors.get(obj.name, [1.0, 1.0, 1.0, 1.0])

            if element.id() not in product_frames:
                # Ocultar objetos que están fuera del rango de visualización
                obj.hide_viewport = True
                obj.hide_render = True
                continue

            for frame_data in product_frames[element.id()]:
                task = frame_data.get("task") or tool.Ifc.get().by_id(frame_data.get("task_id"))
                profile = cls.get_assigned_profile_for_task(task, animation_props, active_group_name)
                if not profile:
                    predefined_type = getattr(task, "PredefinedType", None) or "NOTDEFINED"
                    profile = cls.load_profile_from_group(active_group_name, predefined_type) or cls.create_generic_profile(predefined_type)
                cls.apply_profile_animation(obj, frame_data, profile, original_color, settings)

        area = tool.Blender.get_view3d_area()
        try:
            area.spaces[0].shading.color_type = "OBJECT"
        except Exception:
            pass
        bpy.context.scene.frame_start = settings["start_frame"]
        bpy.context.scene.frame_end = int(settings["start_frame"] + settings["total_frames"] + 1)

    @classmethod
    def create_generic_profile(cls, predefined_type):
        return type('AppearanceProfile', (object,), {
            'name': predefined_type,
            'consider_start': True,
            'consider_active': True,
            'consider_end': True,
            'start_color': [1, 1, 1, 0],
            'in_progress_color': [1, 0.5, 0, 1],
            'end_color': [0.8, 0.8, 0.8, 1],
            'use_start_original_color': False,
            'use_active_original_color': False,
            'use_end_original_color': True,
            'start_transparency': 0.0,
            'active_start_transparency': 0.0,
            'active_finish_transparency': 0.0,
            'active_transparency_interpol': 1.0,
            'end_transparency': 0.0,
            'hide_at_end': (predefined_type in {"DEMOLITION","REMOVAL","DISPOSAL","DISMANTLE"}),
        })()
    @classmethod
    def debug_profile_application(cls, obj, profile, frame_data):
        """Debug helper para verificar aplicación de perfiles"""
        print(f"🔍 DEBUG Profile Application:")
        print(f"   Object: {obj.name}")
        print(f"   Profile: {getattr(profile, 'name', 'Unknown')}")
        print(f"   consider_start: {getattr(profile, 'consider_start', False)}")
        print(f"   consider_active: {getattr(profile, 'consider_active', True)}")
        print(f"   consider_end: {getattr(profile, 'consider_end', True)}")
        print(f"   Frame states: {frame_data.get('states', {})}")
        print(f"   Relationship: {frame_data.get('relationship', 'unknown')}")

    # ==================================================================
    # === 2. FUNCIÓN CORREGIDA (APLICACIÓN DE PERFIL) ==================
    # ==================================================================
    @classmethod
    def apply_profile_animation(cls, obj, frame_data, profile, original_color, settings):
        """
        Aplica la animación a un objeto basándose en su perfil de apariencia,
        con la lógica corregida para todos los casos de uso.
        """
        if frame_data.get("consider_start_active", False):
            print(f"🔒 {obj.name}: Aplicando perfil de rango completo (Start prioritario).")
            start_f, end_f = frame_data["states"]["active"]
            cls.apply_state_appearance(obj, profile, "start", start_f, end_f, original_color, frame_data)
            return

        # Lógica secuencial normal
        print(f"📋 {obj.name}: Aplicando perfil secuencial basado en fechas.")
        has_consider_start = getattr(profile, 'consider_start', True)
        is_active_considered = getattr(profile, 'consider_active', True)
        is_end_considered = getattr(profile, 'consider_end', True)

        for state_name, (start_f, end_f) in frame_data["states"].items():
            if end_f < start_f:
                continue

            state_map = {"before_start": "start", "active": "in_progress", "after_end": "end"}
            state = state_map.get(state_name)
            if not state:
                continue

            # === CORRECCIÓN CLAVE ===
            # Se separa la lógica de "start" para manejar la ocultación explícita.
            if state == "start":
                if not has_consider_start:
                    # Si 'Start' NO se considera y es un objeto de construcción ('output'),
                    # debe estar OCULTO hasta que empiece su fase 'Active'.
                    if frame_data.get("relationship") == "output":
                        obj.hide_viewport = True
                        obj.hide_render = True
                        obj.keyframe_insert(data_path="hide_viewport", frame=start_f)
                        obj.keyframe_insert(data_path="hide_render", frame=start_f)
                        if end_f > start_f:
                            obj.keyframe_insert(data_path="hide_viewport", frame=end_f)
                            obj.keyframe_insert(data_path="hide_render", frame=end_f)
                    # Para inputs (demolición), no hacer nada los mantiene visibles, que es lo correcto.
                    continue  # Pasar al siguiente estado.
                # Si 'Start' SÍ se considera, aplicar su apariencia.
                cls.apply_state_appearance(obj, profile, "start", start_f, end_f, original_color, frame_data)

            elif state == "in_progress":
                if not is_active_considered:
                    continue
                cls.apply_state_appearance(obj, profile, "in_progress", start_f, end_f, original_color, frame_data)

            elif state == "end":
                if not is_end_considered:
                    continue
                cls.apply_state_appearance(obj, profile, "end", start_f, end_f, original_color, frame_data)
    @classmethod
    def apply_state_appearance(cls, obj, profile, state, start_frame, end_frame, original_color, frame_data=None):
        """CORRECCIÓN: Mejorar manejo del estado start para elementos persistentes"""
        if state == "start":
            # CORRECCIÓN: Cuando consider_start=True, el objeto debe ser siempre visible
            obj.hide_viewport = False
            obj.hide_render = False
            obj.keyframe_insert(data_path="hide_viewport", frame=start_frame)
            obj.keyframe_insert(data_path="hide_render", frame=start_frame)

            # Si hay end_frame diferente, asegurar visibilidad durante todo el rango
            if end_frame > start_frame:
                obj.keyframe_insert(data_path="hide_viewport", frame=end_frame)
                obj.keyframe_insert(data_path="hide_render", frame=end_frame)

            use_original = getattr(profile, 'use_start_original_color', False)
            color = original_color if use_original else list(profile.start_color[:])
            transparency = getattr(profile, 'start_transparency', 0.0)

            alpha = 1.0 - transparency
            obj.color = (color[0], color[1], color[2], alpha)
            obj.keyframe_insert(data_path="color", frame=start_frame)

            # Mantener color durante todo el rango si es necesario
            if end_frame > start_frame:
                obj.keyframe_insert(data_path="color", frame=end_frame)

            print(f"✅ Aplicado estado start a {obj.name} desde frame {start_frame} hasta {end_frame}")

        elif state == "in_progress":
            obj.hide_viewport = False
            obj.hide_render = False
            obj.keyframe_insert(data_path="hide_viewport", frame=start_frame)
            obj.keyframe_insert(data_path="hide_render", frame=start_frame)

            use_original = getattr(profile, 'use_active_original_color', False)
            color = original_color if use_original else list(profile.in_progress_color[:])

            start_transparency = getattr(profile, 'active_start_transparency', 0.0)
            end_transparency = getattr(profile, 'active_finish_transparency', 0.0)
            interpol_mode = getattr(profile, 'active_transparency_interpol', 1.0)

            alpha_start = 1.0 - start_transparency
            obj.color = (color[0], color[1], color[2], alpha_start)
            obj.keyframe_insert(data_path="color", frame=start_frame)

            if end_frame > start_frame:
                alpha_end = 1.0 - end_transparency
                obj.color = (color[0], color[1], color[2], alpha_end)
                obj.keyframe_insert(data_path="color", frame=end_frame)

                if obj.animation_data and obj.animation_data.action:
                    for fcurve in obj.animation_data.action.fcurves:
                        if fcurve.data_path == "color" and fcurve.array_index == 3:
                            for kf in fcurve.keyframe_points:
                                if int(kf.co[0]) in [start_frame, end_frame]:
                                    if interpol_mode < 0.5:
                                        kf.interpolation = 'CONSTANT'
                                    else:
                                        kf.interpolation = 'LINEAR'

        elif state == "end":
            # <-- INICIO DE LA MODIFICACIÓN -->
            # Priorizar la nueva opción del perfil para ocultar el objeto al final.
            should_hide = getattr(profile, 'hide_at_end', False)

            if should_hide:
                # Si el perfil lo indica, ocultar el objeto.
                # Ideal para demoliciones donde el elemento debe desaparecer.
                obj.hide_viewport = True
                obj.hide_render = True
                obj.keyframe_insert(data_path="hide_viewport", frame=start_frame)
                obj.keyframe_insert(data_path="hide_render", frame=start_frame)
                print(f"✅ Objeto {obj.name} ocultado en el frame {start_frame} según el perfil.")
            else:
                # Lógica anterior: mostrar el objeto con su apariencia de fin.
                # Útil para construcción o elementos que permanecen visibles.
                obj.hide_viewport = False
                obj.hide_render = False
                obj.keyframe_insert(data_path="hide_viewport", frame=start_frame)
                obj.keyframe_insert(data_path="hide_render", frame=start_frame)

                use_original = getattr(profile, 'use_end_original_color', True)
                color = original_color if use_original else list(profile.end_color[:])
                transparency = getattr(profile, 'end_transparency', 0.0)

                alpha = 1.0 - transparency
                final_color = (color[0], color[1], color[2], alpha)

                obj.color = final_color
                obj.keyframe_insert(data_path="color", frame=start_frame)
            # <-- FIN DE LA MODIFICACIÓN -->

    @classmethod
    def get_product_frames_with_profiles(cls, work_schedule, settings):
            """Versión mejorada con soporte de perfiles y 'states' compatibles.
            Si existe el método 'get_animation_product_frames_enhanced', lo utiliza y retorna su estructura,
            garantizando así compatibilidad con apply_profile_animation.
            """
            # Garantiza grupo DEFAULT si el usuario no configuró nada
            try:
                from bonsai.bim.module.sequence.prop import UnifiedProfileManager
                UnifiedProfileManager.ensure_default_group(bpy.context)
            except Exception:
                pass

            # Preferimos la ruta 'enhanced' existente para mantener compatibilidad
            try:
                frames = cls.get_animation_product_frames_enhanced(work_schedule, settings)
                if isinstance(frames, dict):
                    return frames
            except Exception:
                pass

            # Fallback: construir producto->frames con estados mínimos a partir del método básico
            basic = cls.get_animation_product_frames(work_schedule, settings)
            product_frames = {}
            for pid, items in (basic or {}).items():
                product_frames[pid] = []
                for it in items:
                    start_f = it.get("STARTED")
                    finish_f = it.get("COMPLETED")
                    if start_f is None or finish_f is None:
                        continue
                    product_frames[pid].append({
                        "task": None,
                        "task_id": 0,
                        "type": it.get("type") or "NOTDEFINED",
                        "relationship": it.get("relationship") or "output",
                        "start_date": settings.get("start"),
                        "finish_date": settings.get("finish"),
                        "STARTED": start_f,
                        "COMPLETED": finish_f,
                        "start_frame": start_f,
                        "finish_frame": finish_f,
                        "states": {
                            "before_start": (settings["start_frame"], max(settings["start_frame"], int(start_f) - 1)),
                            "active": (int(start_f), int(finish_f)),
                            "after_end": (min(int(finish_f) + 1, int(settings["start_frame"] + settings["total_frames"])), int(settings["start_frame"] + settings["total_frames"])),
                        },
                    })
            return product_frames

    @classmethod
    def _process_task_with_profiles(cls, task, settings, product_frames, anim_props, profile_cache):
            """Procesa recursivamente una tarea, agregando frames con estados.
            Mantiene compatibilidad con la estructura 'enhanced'."""
            for subtask in ifcopenshell.util.sequence.get_nested_tasks(task):
                cls._process_task_with_profiles(subtask, settings, product_frames, anim_props, profile_cache)

            # Fechas
            start = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
            finish = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)
            if not start or not finish:
                return

            # Precalcular frames
            start_frame = round(settings["start_frame"] + (((start - settings["start"]) / settings["duration"]) * settings["total_frames"]))
            finish_frame = round(settings["start_frame"] + (((finish - settings["start"]) / settings["duration"]) * settings["total_frames"]))

            # Cache de perfil (aunque el perfil puede resolverse en apply)
            task_id = task.id()
            if task_id not in profile_cache:
                profile_cache[task_id] = cls._get_best_profile_for_task(task, anim_props)

            def _add(pid, relationship):
                product_frames.setdefault(pid, []).append({
                    "task": task,
                    "task_id": task.id(),
                    "type": task.PredefinedType or "NOTDEFINED",
                    "relationship": relationship,
                    "start_date": start,
                    "finish_date": finish,
                    "STARTED": start_frame,
                    "COMPLETED": finish_frame,
                    "start_frame": start_frame,
                    "finish_frame": finish_frame,
                    "states": {
                        "before_start": (settings["start_frame"], max(settings["start_frame"], start_frame - 1)),
                        "active": (start_frame, finish_frame),
                        "after_end": (min(finish_frame + 1, int(settings["start_frame"] + settings["total_frames"])), int(settings["start_frame"] + settings["total_frames"])),
                    },
                })

            for output in ifcopenshell.util.sequence.get_task_outputs(task):
                _add(output.id(), "output")
            for input_prod in cls.get_task_inputs(task):
                _add(input_prod.id(), "input")


    @classmethod
    def _get_best_profile_for_task(cls, task, anim_props):
            """Determina el perfil más apropiado para una tarea considerando la pila de grupos y elección por tarea."""
            try:
                # Determinar el grupo activo (primer grupo habilitado en el stack) o DEFAULT
                agn = None
                for it in getattr(anim_props, 'animation_group_stack', []):
                    if getattr(it, 'enabled', False) and getattr(it, 'group', None):
                        agn = it.group
                        break
                if not agn:
                    agn = 'DEFAULT'
                profile = cls.get_assigned_profile_for_task(task, anim_props, agn)
                if profile:
                    return profile
            except Exception:
                pass
            predefined_type = task.PredefinedType or "NOTDEFINED"
            # Intentar en DEFAULT
            try:
                prof = cls.load_profile_from_group("DEFAULT", predefined_type)
                if prof:
                    return prof
            except Exception:
                pass
            # Fallback genérico
            return cls.create_generic_profile(predefined_type)

    @classmethod
    def _task_has_consider_start_profile(cls, task):
        """Helper to check if a task's resolved profile has consider_start=True."""
        try:
            # Re-use existing logic to find the best profile for the task
            anim_props = cls.get_animation_props()
            profile = cls._get_best_profile_for_task(task, anim_props)
            return getattr(profile, 'consider_start', False)
        except Exception as e:
            print(f"⚠️ Error in _task_has_consider_start_profile for task {getattr(task, 'Name', 'N/A')}: {e}")
            return False

    @classmethod
    def _apply_profile_to_object(cls, obj, frame_data, profile, original_color, settings):
            for state_name, (start_f, end_f) in frame_data["states"].items():
                if end_f < start_f:
                    continue
                if state_name == "before_start":
                    state = "start"
                elif state_name == "active":
                    state = "in_progress"
                elif state_name == "after_end":
                    state = "end"
                else:
                    continue
                if state == "start" and not getattr(profile, 'consider_start', True):
                    if frame_data.get("relationship") == "output":
                        obj.hide_viewport = True
                        obj.hide_render = True
                        obj.keyframe_insert(data_path="hide_viewport", frame=start_f)
                        obj.keyframe_insert(data_path="hide_render", frame=start_f)
                    return
                elif state == "in_progress" and not getattr(profile, 'consider_active', True):
                    return
                elif state == "end" and not getattr(profile, 'consider_end', True):
                    return
                cls.apply_state_appearance(obj, profile, state, start_f, end_f, original_color, frame_data)
                # Transparencia: fade durante tramo activo
                try:
                    if state == 'in_progress':
                        vals0 = _seq_data.interpolate_profile_values(profile, 'in_progress', 0.0)
                        vals1 = _seq_data.interpolate_profile_values(profile, 'in_progress', 1.0)
                        a0 = float(vals0.get('alpha', obj.color[3] if len(obj.color) >= 4 else 1.0))
                        a1 = float(vals1.get('alpha', a0))
                        # Keyframes al inicio y fin del tramo activo
                        c = list(obj.color)
                        if len(c) < 4:
                            c = [c[0], c[1], c[2], 1.0]
                        c[3] = a0
                        obj.color = c
                        obj.keyframe_insert(data_path='color', frame=int(start_f))
                        c[3] = a1
                        obj.color = c
                        obj.keyframe_insert(data_path='color', frame=int(end_f))
                except Exception:
                    pass

            # === Multi-Text 4D Display System ===
            _frame_change_handler = None

    @classmethod
    def add_text_animation_handler(cls, settings):
            """Crea múltiples objetos de texto animados para mostrar información del cronograma"""

            from datetime import timedelta

            collection_name = "Schedule_Display_Texts"
            if collection_name in bpy.data.collections:
                collection = bpy.data.collections[collection_name]
                # Limpiar objetos anteriores
                for obj in list(collection.objects):
                    try:
                        bpy.data.objects.remove(obj, do_unlink=True)
                    except Exception:
                        pass
            else:
                collection = bpy.data.collections.new(collection_name)
                try:
                    bpy.context.scene.collection.children.link(collection)
                except Exception:
                    pass

            text_configs = [
                {"name": "Schedule_Date","position": (0, 10, 5),"size": 1.2,"align": "CENTER","color": (1, 1, 1, 1),"type": "date"},
                {"name": "Schedule_Week","position": (0, 10, 4),"size": 1.0,"align": "CENTER","color": (0.8, 0.8, 1, 1),"type": "week"},
                {"name": "Schedule_Day_Counter","position": (0, 10, 3),"size": 0.8,"align": "CENTER","color": (1, 1, 0.8, 1),"type": "day_counter"},
                {"name": "Schedule_Progress","position": (0, 10, 2),"size": 1.0,"align": "CENTER","color": (0.8, 1, 0.8, 1),"type": "progress"},
            ]

            created_texts = []
            for config in text_configs:
                text_obj = cls._create_animated_text(config, settings, collection)
                created_texts.append(text_obj)

            # Auto-configurar HUD si hay cámara 4D activa
            try:
                scene = bpy.context.scene
                if scene.camera and "4D_Animation_Camera" in scene.camera.name:
                    anim_props = cls.get_animation_props()
                    camera_props = anim_props.camera_orbit

                    # Solo auto-habilitar si no está ya configurado
                    if not getattr(camera_props, "enable_text_hud", False):
                        print("🎯 Auto-enabling HUD for new schedule texts...")
                        camera_props.enable_text_hud = True

                        # Setup diferido para asegurar que los textos estén completamente creados
                        def setup_hud_deferred():
                            try:
                                bpy.ops.bim.setup_text_hud()
                                print("✅ Deferred HUD setup completed")
                            except Exception as e:
                                print(f"Deferred HUD setup failed: {e}")

                        bpy.app.timers.register(setup_hud_deferred, first_interval=0.3)
                    else:
                        # Si ya está habilitado, solo actualizar posiciones
                        def update_hud_deferred():
                            try:
                                bpy.ops.bim.update_text_hud_positions()
                            except Exception as e:
                                print(f"HUD position update failed: {e}")

                        bpy.app.timers.register(update_hud_deferred, first_interval=0.1)

            except Exception as e:
                print(f"Error in auto-HUD setup: {e}")
            cls._register_multi_text_handler(settings)
            return created_texts

    @classmethod
    def _create_animated_text(cls, config, settings, collection):

            text_curve = bpy.data.curves.new(name=config["name"], type='FONT')
            text_curve.size = config["size"]
            text_curve.align_x = config["align"]
            text_curve.align_y = 'CENTER'

            text_curve["text_type"] = config["type"]
            # Guardar algunos campos primitivos (no objetos complejos)
            try:
                start = settings.get("start") if isinstance(settings, dict) else getattr(settings, "start", None)
                finish = settings.get("finish") if isinstance(settings, dict) else getattr(settings, "finish", None)
                start_frame = int(settings.get("start_frame", 1)) if isinstance(settings, dict) else int(getattr(settings, "start_frame", 1))
                total_frames = int(settings.get("total_frames", 250)) if isinstance(settings, dict) else int(getattr(settings, "total_frames", 250))
                # Convertir datetime a ISO si es necesario
                if hasattr(start, "isoformat"):
                    start_iso = start.isoformat()
                else:
                    start_iso = str(start)
                if hasattr(finish, "isoformat"):
                    finish_iso = finish.isoformat()
                else:
                    finish_iso = str(finish)
            except Exception:
                start_iso = ""
            text_curve["animation_settings"] = {
                "start_frame": start_frame,
                "total_frames": total_frames,
                "start_date": start_iso,
                "finish_date": finish_iso,
            }

            text_obj = bpy.data.objects.new(name=config["name"], object_data=text_curve)
            try:
                collection.objects.link(text_obj)
            except Exception:
                try:
                    bpy.context.scene.collection.objects.link(text_obj)
                except Exception:
                    pass
            text_obj.location = config["position"]
            cls._setup_text_material_colored(text_obj, config["color"], config["name"])
            cls._animate_text_by_type(text_obj, config["type"], settings)
            return text_obj

    @classmethod
    def _setup_text_material_colored(cls, text_obj, color, mat_name_suffix):

            mat_name = f"Schedule_Text_Mat_{mat_name_suffix}"
            mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(name=mat_name)
            try:
                mat.use_nodes = True
                nt = mat.node_tree
                bsdf = nt.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Base Color"].default_value = tuple(list(color[:3]) + [1.0])
                    bsdf.inputs["Emission"].default_value = tuple(list(color[:3]) + [1.0])
                    bsdf.inputs["Emission Strength"].default_value = 1.5
            except Exception:
                pass
            try:
                text_obj.data.materials.clear()
                text_obj.data.materials.append(mat)
            except Exception:
                pass

    @classmethod
    def _animate_text_by_type(cls, text_obj, text_type, settings):

            from datetime import timedelta, datetime as _dt

            start_date = settings.get("start") if isinstance(settings, dict) else getattr(settings, "start", None)
            finish_date = settings.get("finish") if isinstance(settings, dict) else getattr(settings, "finish", None)
            start_frame = int(settings.get("start_frame", 1)) if isinstance(settings, dict) else int(getattr(settings, "start_frame", 1))
            total_frames = int(settings.get("total_frames", 250)) if isinstance(settings, dict) else int(getattr(settings, "total_frames", 250))

            if isinstance(start_date, str):
                try:
                    from dateutil import parser as _parser
                    start_date = _dt.fromisoformat(start_date.replace(' ', 'T')[:19]) if '-' in start_date else _parser.parse(start_date, yearfirst=True)
                except Exception:
                    start_date = _dt.now()
            if isinstance(finish_date, str):
                try:
                    from dateutil import parser as _parser
                    finish_date = _dt.fromisoformat(finish_date.replace(' ', 'T')[:19]) if '-' in finish_date else _parser.parse(finish_date, yearfirst=True)
                except Exception:
                    finish_date = start_date

            duration = finish_date - start_date
            step_days = 7 if duration.days > 365 else (3 if duration.days > 90 else 1)

            current_date = start_date
            while current_date <= finish_date:
                if duration.total_seconds() > 0:
                    progress = (current_date - start_date).total_seconds() / duration.total_seconds()
                else:
                    progress = 0.0
                frame = start_frame + (progress * total_frames)

                if text_type == "date":
                    text_content = cls._format_date(current_date)
                elif text_type == "week":
                    text_content = cls._format_week(current_date, start_date)
                elif text_type == "day_counter":
                    text_content = cls._format_day_counter(current_date, start_date, finish_date)
                elif text_type == "progress":
                    text_content = cls._format_progress(current_date, start_date, finish_date)
                else:
                    text_content = ""

                text_obj.data.body = text_content
                try:
                    text_obj.data.keyframe_insert(data_path="body", frame=int(frame))
                except Exception:
                    pass

                current_date += timedelta(days=step_days)
                if current_date > finish_date and current_date - timedelta(days=step_days) < finish_date:
                    current_date = finish_date

    @classmethod
    def _format_date(cls, current_date):
            try:
                return current_date.strftime("%d %B %Y")
            except Exception:
                return str(current_date)

    @classmethod
    def _format_week(cls, current_date, start_date):
            try:
                days_elapsed = (current_date - start_date).days
                current_week = (days_elapsed // 7) + 1
                day_of_week = current_date.strftime("%A")
                return f"Week {current_week} - {day_of_week}"
            except Exception:
                return "Week ?"

    @classmethod
    def _format_day_counter(cls, current_date, start_date, finish_date):
            try:
                days_elapsed = (current_date - start_date).days + 1
                total_days = (finish_date - start_date).days + 1
                return f"Day {days_elapsed} of {total_days}"
            except Exception:
                return "Day ?"

    @classmethod
    def _format_progress(cls, current_date, start_date, finish_date):
            try:
                total = (finish_date - start_date).days
                if total > 0:
                    progress = ((current_date - start_date).days / total) * 100.0
                else:
                    progress = 100.0
                bar_length = 20
                filled = int(bar_length * max(0.0, min(100.0, progress)) / 100.0)
                bar = "█" * filled + "░" * (bar_length - filled)
                return f"Progress: {progress:.1f}%\n{bar}"
            except Exception:
                return "Progress: ?"

    @classmethod
    def _register_multi_text_handler(cls, settings):

            from datetime import datetime as _dt

            cls._unregister_frame_change_handler()

            def update_all_schedule_texts(scene):
                collection_name = "Schedule_Display_Texts"
                coll = bpy.data.collections.get(collection_name)
                if not coll:
                    return
                current_frame = int(scene.frame_current)
                for text_obj in list(coll.objects):
                    anim_settings = text_obj.data.get("animation_settings") if getattr(text_obj, "data", None) else None
                    if not anim_settings:
                        continue
                    start_frame = int(anim_settings.get("start_frame", 1))
                    total_frames = int(anim_settings.get("total_frames", 250))
                    if current_frame < start_frame:
                        progress = 0.0
                    elif current_frame > start_frame + total_frames:
                        progress = 1.0
                    else:
                        progress = (current_frame - start_frame) / float(total_frames or 1)

                    try:
                        start_date = _dt.fromisoformat(anim_settings.get("start_date"))
                        finish_date = _dt.fromisoformat(anim_settings.get("finish_date"))
                    except Exception:
                        continue
                    duration = finish_date - start_date
                    current_date = start_date + (duration * progress)

                    ttype = text_obj.data.get("text_type", "date")
                    if ttype == "date":
                        text_obj.data.body = cls._format_date(current_date)
                    elif ttype == "week":
                        text_obj.data.body = cls._format_week(current_date, start_date)
                    elif ttype == "day_counter":
                        text_obj.data.body = cls._format_day_counter(current_date, start_date, finish_date)
                    elif ttype == "progress":
                        text_obj.data.body = cls._format_progress(current_date, start_date, finish_date)

            bpy.app.handlers.frame_change_post.append(update_all_schedule_texts)
            cls._frame_change_handler = update_all_schedule_texts

    @classmethod
    def _unregister_frame_change_handler(cls):
            try:

                if getattr(cls, "_frame_change_handler", None) in bpy.app.handlers.frame_change_post:
                    bpy.app.handlers.frame_change_post.remove(cls._frame_change_handler)
            except Exception:
                pass
            cls._frame_change_handler = None

    @classmethod
    def clear_objects_animation(
            cls,
            include_blender_objects: bool = True,
            *,
            clear_texts: bool = True,
            clear_bars: bool = True,
            reset_timeline: bool = True,
            reset_colors_and_visibility: bool = True,
        ):
        """Limpia la animación 4D de forma selectiva y robusta."""

        # 1. Desregistrar handlers de actualización por frame para evitar errores
        cls._unregister_frame_change_handler()

        # 2. Limpiar textos del cronograma
        if clear_texts:
            coll = bpy.data.collections.get("Schedule_Display_Texts")
            if coll:
                for obj in list(coll.objects):
                    bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.collections.remove(coll)

        # 3. Limpiar barras de Gantt 3D
        if clear_bars:
            coll = bpy.data.collections.get("Bar Visual")
            if coll:
                for obj in list(coll.objects):
                    bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.collections.remove(coll)

        # 4. Limpiar objetos 3D (productos del IFC)
        if include_blender_objects:
            for obj in bpy.data.objects:
                if obj.type == 'MESH':
                    if obj.animation_data:
                        obj.animation_data_clear()
                    if reset_colors_and_visibility:
                        obj.hide_viewport = False  # ← ASEGURAR QUE ESTÉ VISIBLE
                        obj.hide_render = False    # ← ASEGURAR QUE ESTÉ VISIBLE
                        obj.color = (0.8, 0.8, 0.8, 1.0) # Reset a un color gris neutro

        # 5. Resetear la línea de tiempo
        if reset_timeline:
            scene = bpy.context.scene
            scene.frame_current = scene.frame_start

        print("✅ Animation data cleared.")

    @classmethod
    def get_tasks_for_product(cls, product, work_schedule=None):
        """
        Obtiene las tareas de entrada y salida para un producto específico.

        Args:
            product: El producto IFC
            work_schedule: El cronograma de trabajo (opcional)

        Returns:
            tuple: (task_inputs, task_outputs)
        """
        try:
            # Usar los métodos existentes para encontrar tareas relacionadas
            input_tasks = cls.find_related_input_tasks(product)
            output_tasks = cls.find_related_output_tasks(product)

            # Si se proporciona work_schedule, filtrar solo las tareas de ese cronograma
            if work_schedule:
                # Obtener todas las tareas controladas por el work_schedule
                controlled_task_ids = set()
                for rel in work_schedule.Controls or []:
                    for obj in rel.RelatedObjects:
                        if obj.is_a("IfcTask"):
                            controlled_task_ids.add(obj.id())

                # Filtrar las tareas de entrada
                filtered_input_tasks = []
                for task in input_tasks:
                    if task.id() in controlled_task_ids:
                        filtered_input_tasks.append(task)

                # Filtrar las tareas de salida
                filtered_output_tasks = []
                for task in output_tasks:
                    if task.id() in controlled_task_ids:
                        filtered_output_tasks.append(task)

                return filtered_input_tasks, filtered_output_tasks

            return input_tasks, output_tasks

        except Exception as e:
            print(f"Error en get_tasks_for_product: {e}")
            return [], []

    @classmethod
    def load_product_related_tasks(cls, product):
        """
        Carga las tareas relacionadas con un producto y las muestra en la UI.

        Args:
            product: El producto IFC para el cual buscar tareas

        Returns:
            str: Mensaje de resultado o lista de tareas
        """
        try:
            props = cls.get_work_schedule_props()

            # Obtener el work_schedule activo si existe
            active_work_schedule = None
            if props.active_work_schedule_id:
                active_work_schedule = tool.Ifc.get().by_id(props.active_work_schedule_id)

            # Llamar al método con el work_schedule
            task_inputs, task_outputs = cls.get_tasks_for_product(product, active_work_schedule)

            # Limpiar las listas existentes
            props.product_input_tasks.clear()
            props.product_output_tasks.clear()

            # Cargar tareas de entrada
            for task in task_inputs:
                new_input = props.product_input_tasks.add()
                new_input.ifc_definition_id = task.id()
                new_input.name = task.Name or "Unnamed"

            # Cargar tareas de salida
            for task in task_outputs:
                new_output = props.product_output_tasks.add()
                new_output.ifc_definition_id = task.id()
                new_output.name = task.Name or "Unnamed"

            total_tasks = len(task_inputs) + len(task_outputs)

            if total_tasks == 0:
                return "No related tasks found for this product"

            return f"Found {len(task_inputs)} input tasks and {len(task_outputs)} output tasks"

        except Exception as e:
            print(f"Error in load_product_related_tasks: {e}")
            return f"Error loading tasks: {str(e)}"

    @classmethod
    def validate_task_object(cls, task, operation_name="operation"):
        """
        Valida que un objeto tarea sea válido antes de procesarlo.

        Args:
            task: El objeto tarea a validar
            operation_name: Nombre de la operación para logging

        Returns:
            bool: True si la tarea es válida, False en caso contrario
        """
        if task is None:
            print(f"⚠️ Warning: None task in {operation_name}")
            return False

        if not hasattr(task, 'id') or not callable(getattr(task, 'id', None)):
            print(f"⚠️ Warning: Invalid task object in {operation_name}: {task}")
            return False

        try:
            task_id = task.id()
            if task_id is None or task_id <= 0:
                print(f"⚠️ Warning: Invalid task ID in {operation_name}: {task_id}")
                return False
        except Exception as e:
            print(f"⚠️ Error getting task ID in {operation_name}: {e}")
            return False

        return True


    @classmethod
    def get_work_schedule_products(cls, work_schedule: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        """
        Obtiene todos los productos asociados a un cronograma de trabajo.

        Args:
            work_schedule: El cronograma de trabajo IFC

        Returns:
            Lista de productos IFC (puede ser vacía)
        """
        try:
            products: list[ifcopenshell.entity_instance] = []

            # Obtener todas las tareas del cronograma
            if hasattr(work_schedule, 'Controls') and work_schedule.Controls:
                for rel in work_schedule.Controls:
                    for task in rel.RelatedObjects:
                        if task.is_a("IfcTask"):
                            # Obtener productos de salida (outputs)
                            task_outputs = cls.get_task_outputs(task) or []
                            products.extend(task_outputs)

                            # Obtener productos de entrada (inputs)
                            task_inputs = cls.get_task_inputs(task) or []
                            products.extend(task_inputs)

            # Eliminar duplicados manteniendo el orden
            seen: set[int] = set()
            unique_products: list[ifcopenshell.entity_instance] = []
            for product in products:
                try:
                    pid = product.id()
                except Exception:
                    pid = None
                if pid and pid not in seen:
                    seen.add(pid)
                    unique_products.append(product)

            return unique_products

        except Exception as e:
            print(f"Error getting work schedule products: {e}")
            return []

    @classmethod
    def select_work_schedule_products(cls, work_schedule: ifcopenshell.entity_instance) -> str:
        """
        Selecciona todos los productos asociados a un cronograma de trabajo.

        Args:
            work_schedule: El cronograma de trabajo IFC

        Returns:
            Mensaje de resultado
        """
        try:
            products = cls.get_work_schedule_products(work_schedule)

            if not products:
                return "No products found in work schedule"

            # Usar la función segura de spatial para seleccionar productos
            tool.Spatial.select_products(products)

            return f"Selected {len(products)} products from work schedule"

        except Exception as e:
            print(f"Error selecting work schedule products: {e}")
            return f"Error selecting products: {str(e)}"

    @classmethod
    def select_unassigned_work_schedule_products(cls) -> str:
        """
        Selecciona productos que no están asignados a ningún cronograma de trabajo.

        Returns:
            Mensaje de resultado
        """
        try:
            ifc_file = tool.Ifc.get()
            if not ifc_file:
                return "No IFC file loaded"

            # Obtener todos los productos
            all_products = list(ifc_file.by_type("IfcProduct"))

            # Obtener productos asignados a cronogramas
            schedule_products: set[int] = set()
            for work_schedule in ifc_file.by_type("IfcWorkSchedule"):
                ws_products = cls.get_work_schedule_products(work_schedule) or []
                for product in ws_products:
                    try:
                        pid = product.id()
                    except Exception:
                        pid = None
                    if pid:
                        schedule_products.add(pid)

            # Filtrar productos no asignados
            unassigned_products: list[ifcopenshell.entity_instance] = []
            for product in all_products:
                try:
                    pid = product.id()
                except Exception:
                    pid = None
                if pid and pid not in schedule_products:
                    # Verificar que no sea un elemento espacial
                    try:
                        is_spatial = tool.Root.is_spatial_element(product)
                    except Exception:
                        is_spatial = False
                    if not is_spatial:
                        unassigned_products.append(product)

            if not unassigned_products:
                return "No unassigned products found"

            # Seleccionar productos no asignados
            tool.Spatial.select_products(unassigned_products)

            return f"Selected {len(unassigned_products)} unassigned products"

        except Exception as e:
            print(f"Error selecting unassigned products: {e}")
            return f"Error selecting unassigned products: {str(e)}"

    @classmethod
    def create_tasks_json(cls, work_schedule: ifcopenshell.entity_instance) -> list[dict[str, Any]]:
        sequence_type_map = {
            None: "FS",
            "START_START": "SS",
            "START_FINISH": "SF",
            "FINISH_START": "FS",
            "FINISH_FINISH": "FF",
            "USERDEFINED": "FS",
            "NOTDEFINED": "FS",
        }
        is_baseline = False
        if work_schedule.PredefinedType == "BASELINE":
            is_baseline = True
            relating_work_schedule = work_schedule.IsDeclaredBy[0].RelatingObject
            work_schedule = relating_work_schedule
        tasks_json = []
        for task in ifcopenshell.util.sequence.get_root_tasks(work_schedule):
            if is_baseline:
                cls.create_new_task_json(task, tasks_json, sequence_type_map, baseline_schedule=work_schedule)
            else:
                cls.create_new_task_json(task, tasks_json, sequence_type_map)
        return tasks_json

    @classmethod
    def create_new_task_json(cls, task, json, type_map=None, baseline_schedule=None):
        task_time = task.TaskTime
        resources = ifcopenshell.util.sequence.get_task_resources(task, is_deep=False)

        string_resources = ""
        resources_usage = ""
        for resource in resources:
            string_resources += resource.Name + ", "
            resources_usage += str(resource.Usage.ScheduleUsage) + ", " if resource.Usage else "-, "

        schedule_start = task_time.ScheduleStart if task_time else ""
        schedule_finish = task_time.ScheduleFinish if task_time else ""

        baseline_task = None
        if baseline_schedule:
            for rel in task.Declares:
                for baseline_task in rel.RelatedObjects:
                    if baseline_schedule.id() == ifcopenshell.util.sequence.get_task_work_schedule(baseline_task).id():
                        baseline_task = task
                        break

        if baseline_task and baseline_task.TaskTime:
            compare_start = baseline_task.TaskTime.ScheduleStart
            compare_finish = baseline_task.TaskTime.ScheduleFinish
        else:
            compare_start = schedule_start
            compare_finish = schedule_finish
        task_name = task.Name or "Unnamed"
        task_name = task_name.replace("\n", "")
        data = {
            "pID": task.id(),
            "pName": task_name,
            "pCaption": task_name,
            "pStart": schedule_start,
            "pEnd": schedule_finish,
            "pPlanStart": compare_start,
            "pPlanEnd": compare_finish,
            "pMile": 1 if task.IsMilestone else 0,
            "pRes": string_resources,
            "pComp": 0,
            "pGroup": 1 if task.IsNestedBy else 0,
            "pParent": task.Nests[0].RelatingObject.id() if task.Nests else 0,
            "pOpen": 1,
            "pCost": 1,
            "ifcduration": (
                str(ifcopenshell.util.date.ifc2datetime(task_time.ScheduleDuration))
                if (task_time and task_time.ScheduleDuration)
                else ""
            ),
            "resourceUsage": resources_usage,
        }
        if task_time and task_time.IsCritical:
            data["pClass"] = "gtaskred"
        elif data["pGroup"]:
            data["pClass"] = "ggroupblack"
        elif data["pMile"]:
            data["pClass"] = "gmilestone"
        else:
            data["pClass"] = "gtaskblue"

        data["pDepend"] = ",".join(
            [f"{rel.RelatingProcess.id()}{type_map[rel.SequenceType]}" for rel in task.IsSuccessorFrom or []]
        )
        json.append(data)
        for nested_task in ifcopenshell.util.sequence.get_nested_tasks(task):
            cls.create_new_task_json(nested_task, json, type_map, baseline_schedule)

    @classmethod
    def generate_gantt_browser_chart(
        cls, task_json: list[dict[str, Any]], work_schedule: ifcopenshell.entity_instance
    ) -> None:
        if not bpy.context.scene.WebProperties.is_connected:
            bpy.ops.bim.connect_websocket_server(page="sequencing")
        gantt_data = {"tasks": task_json, "work_schedule": work_schedule.get_info(recursive=True)}
        tool.Web.send_webui_data(data=gantt_data, data_key="gantt_data", event="gantt_data")




class SearchCustomProfileGroup(bpy.types.Operator):
    bl_idname = "bim.search_custom_profile_group"
    bl_label = "Search Custom Profile Group"
    bl_description = "Search and filter custom profile groups"
    bl_options = {"REGISTER", "UNDO"}

    search_term: bpy.props.StringProperty(name="Search", default="")

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        if not self.search_term:
            self.report({'INFO'}, "Enter search term")
            return {'CANCELLED'}

        # Buscar en grupos disponibles
        from bonsai.bim.module.sequence.prop import get_user_created_groups_enum
        items = get_user_created_groups_enum(None, context)

        matches = [item for item in items if self.search_term.lower() in item[1].lower()]

        if matches:
            # Seleccionar el primer match
            props.task_profile_group_selector = matches[0][0]
            self.report({'INFO'}, f"Found and selected: {matches[0][1]}")
        else:
            self.report({'WARNING'}, f"No groups found matching: {self.search_term}")

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "search_term")

class CopyCustomProfileGroup(bpy.types.Operator):
    bl_idname = "bim.copy_custom_profile_group"
    bl_label = "Copy Custom Profile Group"
    bl_description = "Copy current custom profile group to clipboard"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        current_value = getattr(props, "task_profile_group_selector", "")

        if current_value:
            context.window_manager.clipboard = current_value
            self.report({'INFO'}, f"Copied to clipboard: {current_value}")
        else:
            self.report({'WARNING'}, "No custom profile group selected to copy")

        return {'FINISHED'}

class PasteCustomProfileGroup(bpy.types.Operator):
    bl_idname = "bim.paste_custom_profile_group"
    bl_label = "Paste Custom Profile Group"
    bl_description = "Paste custom profile group from clipboard"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        clipboard_value = context.window_manager.clipboard.strip()

        if not clipboard_value:
            self.report({'WARNING'}, "Clipboard is empty")
            return {'CANCELLED'}

        # Verificar que el valor existe en los grupos disponibles
        from bonsai.bim.module.sequence.prop import get_user_created_groups_enum
        items = get_user_created_groups_enum(None, context)
        valid_values = [item[0] for item in items]

        if clipboard_value in valid_values:
            props.task_profile_group_selector = clipboard_value
            self.report({'INFO'}, f"Pasted from clipboard: {clipboard_value}")
        else:
            self.report({'WARNING'}, f"Invalid group in clipboard: {clipboard_value}")

        return {'FINISHED'}

class SetCustomProfileGroupNull(bpy.types.Operator):
    bl_idname = "bim.set_custom_profile_group_null"
    bl_label = "Set Custom Profile Group to Null"
    bl_description = "Clear custom profile group selection (set to null)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()

        # Limpiar la selección
        props.task_profile_group_selector = ""

        # También limpiar el perfil seleccionado en la tarea activa si existe
        try:
            tprops = tool.Sequence.get_task_tree_props()
            wprops = tool.Sequence.get_work_schedule_props()
            if tprops.tasks and wprops.active_task_index < len(tprops.tasks):
                task = tprops.tasks[wprops.active_task_index]
                task.selected_profile_in_active_group = ""
                task.use_active_profile_group = False
        except Exception:
            pass

        self.report({'INFO'}, "Custom profile group cleared (set to null)")
        return {'FINISHED'}

class ShowCustomProfileGroupInfo(bpy.types.Operator):
    bl_idname = "bim.show_custom_profile_group_info"
    bl_label = "Custom Profile Group Info"
    bl_description = "Show information about the current custom profile group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        current_value = getattr(props, "task_profile_group_selector", "")

        if current_value:
            # Obtener información del grupo
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager
            profiles = UnifiedProfileManager.get_group_profiles(context, current_value)

            info_text = f"Group: {current_value}\n"
            info_text += f"Profiles: {len(profiles)}\n"
            if profiles:
                info_text += f"Available: {', '.join(profiles.keys())}"

            self.report({'INFO'}, info_text)
        else:
            self.report({'INFO'}, "No custom profile group selected")

        return {'FINISHED'}
