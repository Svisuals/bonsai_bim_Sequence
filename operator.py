import bpy
import calendar
from datetime import datetime
from dateutil import relativedelta


try:
    from .prop import update_filter_column
except Exception:
    try:
        from bonsai.bim.module.sequence.prop import update_filter_column
    except Exception:
        def update_filter_column(*args, **kwargs):
            pass

class ResetCameraSettings(bpy.types.Operator):
    bl_idname = "bim.reset_camera_settings"
    bl_label = "Reset Camera Settings"
    bl_description = "Reset camera and orbit settings to their default values (HUD and UI settings are preserved)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # --- CORRECCIÓN: Resetear SOLO propiedades de cámara y órbita ---
            camera_props.camera_focal_mm = 35.0
            camera_props.camera_clip_start = 0.1
            camera_props.camera_clip_end = 10000.0
            
            camera_props.orbit_mode = "CIRCLE_360"
            camera_props.orbit_radius_mode = "AUTO"
            camera_props.orbit_radius = 10.0
            camera_props.orbit_height = 8.0
            camera_props.orbit_start_angle_deg = 0.0
            camera_props.orbit_direction = "CCW"
            
            camera_props.look_at_mode = "AUTO"
            camera_props.look_at_object = None
            
            camera_props.orbit_path_shape = 'CIRCLE'
            camera_props.custom_orbit_path = None
            camera_props.interpolation_mode = 'LINEAR'
            camera_props.bezier_smoothness_factor = 0.35
            
            camera_props.orbit_path_method = "FOLLOW_PATH"
            camera_props.orbit_use_4d_duration = True
            camera_props.orbit_duration_frames = 250.0
            camera_props.hide_orbit_path = False
            
            # Las propiedades de HUD, show_3d_schedule_texts y show_camera_orbit_settings
            # ya NO se resetean aquí.

            self.report({'INFO'}, "Camera and orbit settings have been reset")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Reset failed: {str(e)}")
            return {'CANCELLED'}

class Align4DCameraToView(bpy.types.Operator):
    bl_idname = "bim.align_4d_camera_to_view"
    bl_label = "Align Active Camera to View"
    bl_description = "Aligns the active 4D camera to the current 3D view and sets it to static"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.scene or not context.scene.camera:
            return False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                return True
        return False

    def execute(self, context):
        try:
            cam_obj = context.scene.camera
            if not cam_obj:
                self.report({'ERROR'}, "No active camera in scene.")
                return {'CANCELLED'}

            rv3d = None
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    rv3d = area.spaces.active.region_3d
                    break
            
            if not rv3d:
                self.report({'ERROR'}, "No active 3D viewport found.")
                return {'CANCELLED'}

            cam_obj.matrix_world = rv3d.view_matrix.inverted()

            tool.Sequence.clear_camera_animation(cam_obj)
            
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit
            camera_props.orbit_mode = 'NONE'

            if getattr(camera_props, 'enable_text_hud', False):
                try:
                    bpy.ops.bim.refresh_schedule_hud()
                except Exception as e:
                    print(f"HUD refresh after align failed: {e}")
            
            self.report({'INFO'}, "Camera aligned to view and set to static.")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to align camera: {str(e)}")
            return {'CANCELLED'}

# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>, 2022 Yassine Oualid <yassine@sigmadimensions.com>
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
def _get_internal_profile_sets(context):
    scene = context.scene
    key = "BIM_AppearanceProfileSets"
    # Ensure container exists
    if key not in scene:
        scene[key] = json.dumps({})
    # Parse
    try:
        data = json.loads(scene[key])
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    # --- Auto-create DEFAULT group if empty ---
    try:
        if not data:
            default_names = [
                "ATTENDANCE", "CONSTRUCTION", "DEMOLITION", "DISMANTLE",
                "DISPOSAL", "INSTALLATION", "LOGISTIC", "MAINTENANCE",
                "MOVE", "OPERATION", "REMOVAL", "RENOVATION",
            ]
            data = {"DEFAULT": {"profiles": [{"name": n} for n in default_names]}}
            scene[key] = json.dumps(data)
    except Exception:
        pass
    return data

def _set_internal_profile_sets(context, data: dict):
    context.scene["BIM_AppearanceProfileSets"] = json.dumps(data)

# pyright: reportUnnecessaryTypeIgnoreComment=error

import os

def _safe_set(obj, name, value):
    try:
        setattr(obj, name, value)
    except Exception:
        # Silently ignore when the target property doesn't exist
        pass

import bpy
import json
import time
import calendar
import isodate
import bonsai.core.sequence as core
import bonsai.tool as tool
import bonsai.bim.module.sequence.helper as helper
try:
    from bonsai.bim.module.sequence.prop import UnifiedProfileManager
except Exception:
    UnifiedProfileManager = None  # optional
try:
    from bonsai.bim.module.sequence.prop import TaskProfileGroupChoice
except Exception:
    TaskProfileGroupChoice = None  # optional

import ifcopenshell.util.sequence
import ifcopenshell.util.selector
from datetime import datetime
from dateutil import parser, relativedelta
from bpy_extras.io_utils import ImportHelper, ExportHelper

# === Local handler to keep schedule texts in sync with the chosen date range ===
_LOCAL_TEXT_HANDLER = None

def _parse_dt_any(v):
    """Parse 'YYYY-MM-DD' or ISO-like strings to datetime (no external deps)."""
    try:
        # Accept datetime/date objects
        if hasattr(v, 'year') and hasattr(v, 'month') and hasattr(v, 'day'):
            from datetime import datetime as _dt
            # If it's already datetime-like, normalize to datetime
            if hasattr(v, 'hour'):
                return v
            return _dt(v.year, v.month, v.day)
        s = str(v).strip()
        if not s:
            return None
        from datetime import datetime as _dt
        # Full datetime
        try:
            return _dt.fromisoformat(s.replace('Z',''))
        except Exception:
            pass
        # Date-only
        try:
            return _dt.fromisoformat(s.split('T')[0])
        except Exception:
            return None
    except Exception:
        return None

def calculate_schedule_metrics(current_date, schedule_start, schedule_end, config_start=None, config_finish=None):
    '''
    LÓGICA CORREGIDA - TODOS LOS VALORES BASADOS EN CRONOGRAMA COMPLETO.
    Retorna week (>=1), day (>=1), progress (1..100).
    Acepta str o datetime; usa _parse_dt_any para normalizar.
    '''
    try:
        # Normalizar a datetime (mantener solo fecha para evitar desfases por hora)
        cd = _parse_dt_any(current_date)
        ss = _parse_dt_any(schedule_start)
        se = _parse_dt_any(schedule_end)
        if ss is None or se is None or cd is None:
            return None

        cd_d = cd.date()
        ss_d = ss.date()
        se_d = se.date()

        # VALIDACIÓN: si current_date es anterior al inicio, usar schedule_start
        if cd_d < ss_d:
            cd_d = ss_d

        # 1. DAY: desde inicio de cronograma + 1
        delta_days = (cd_d - ss_d).days
        day = max(1, delta_days + 1)

        # 2. WEEK: desde inicio de cronograma + 1
        week = max(1, (delta_days // 7) + 1)

        # 3. PROGRESS: relativo al cronograma completo [1..100]
        total_schedule_days = (se_d - ss_d).days
        elapsed_schedule_days = (cd_d - ss_d).days

        if elapsed_schedule_days <= 0:
            progress = 1
        elif cd_d >= se_d or total_schedule_days <= 0:
            progress = 100
        else:
            progress = 1 + (elapsed_schedule_days / total_schedule_days) * 99
            progress = round(progress)

        return {
            "week": int(max(1, week)),
            "day": int(max(1, day)),
            "progress": int(max(1, min(100, progress))),
        }
    except Exception:
        return None

def _ensure_local_text_settings_on_obj(_obj, _settings):
    """Attach or refresh minimal settings on text data so the handler maps frame→date correctly."""
    try:
        data = getattr(_obj, 'data', None)
        if not data:
            return
        aset = dict(data.get('animation_settings', {}))
        def _get(k, default=None):
            if isinstance(_settings, dict):
                return _settings.get(k, default)
            return getattr(_settings, k, default)

        scene = bpy.context.scene
        new_vals = {
            'start_frame': int(_get('start_frame', getattr(scene, 'frame_start', 1) or 1)),
            'total_frames': int(_get('total_frames', max(1, int(getattr(scene, 'frame_end', 250)) - int(getattr(scene, 'frame_start', 1))))),
            'start_date': _get('start', None),
            'finish_date': _get('finish', None),
            'schedule_start': _get('schedule_start', None),
            'schedule_finish': _get('schedule_finish', None),
        }
        changed = False
        for k, v in new_vals.items():
            if aset.get(k) != v and v is not None:
                aset[k] = v
                changed = True
        if changed:
            data['animation_settings'] = aset

        # Ensure text_type is defined for the handler
        if not data.get('text_type'):
            n = (getattr(_obj, 'name', '') or '').lower()
            if 'date' in n:
                data['text_type'] = 'date'
            elif 'week' in n:
                data['text_type'] = 'week'
            elif 'day' in n:
                data['text_type'] = 'day_counter'
            elif 'progress' in n:
                data['text_type'] = 'progress'
    except Exception:
        pass

def _local_schedule_texts_update_handler(scene, depsgraph):
    '''Update schedule text objects each frame. Week/Day/Progress are based on the FULL schedule (baseline).'''
    try:

        coll = bpy.data.collections.get("Schedule_Display_Texts")
        if not coll:
            return
        cur_frame = int(scene.frame_current)
        for obj in list(coll.objects):
            cdata = getattr(obj, "data", None)
            if not cdata:
                continue
            meta = dict(cdata.get("animation_settings", {})) or {}
            start_frame = int(meta.get("start_frame", scene.frame_start))
            total_frames = int(meta.get("total_frames", max(1, scene.frame_end - scene.frame_start)))
            if total_frames <= 0:
                total_frames = 1
            # Normalized progress along the configured WINDOW
            prog = (cur_frame - start_frame) / float(total_frames)
            prog = max(0.0, min(1.0, prog))

            # Window dates for mapping frame -> current date
            wnd_start = _parse_dt_any(meta.get("start_date"))
            wnd_finish = _parse_dt_any(meta.get("finish_date"))
            cur_dt = None
            if wnd_start and wnd_finish:
                try:
                    delta_w = (wnd_finish - wnd_start)
                    cur_dt = wnd_start + prog * delta_w
                except Exception:
                    cur_dt = wnd_start

            # Baseline schedule dates (full range)
            sch_start = _parse_dt_any(meta.get("schedule_start"))
            sch_finish = _parse_dt_any(meta.get("schedule_finish"))
            if not sch_start or not sch_finish:
                # Try to infer from active work schedule if missing
                try:
                    ws = tool.Sequence.get_work_schedule_props()
                    ws_obj = tool.Ifc.get().by_id(getattr(ws, "active_work_schedule_id", 0))
                    ss, sf = _infer_schedule_date_range(ws_obj) if ws_obj else (None, None)
                    if ss and (not sch_start or ss < sch_start): sch_start = ss
                    if sf and (not sch_finish or sf > sch_finish): sch_finish = sf
                except Exception:
                    pass
                # Lastly, check global animation settings (do NOT fall back to window)
                try:
                    _aset = tool.Sequence.get_animation_settings()
                    if isinstance(_aset, dict):
                        sch_start = sch_start or _parse_dt_any(_aset.get('schedule_start'))
                        sch_finish = sch_finish or _parse_dt_any(_aset.get('schedule_finish'))
                    else:
                        sch_start = sch_start or _parse_dt_any(getattr(_aset, 'schedule_start', None))
                        sch_finish = sch_finish or _parse_dt_any(getattr(_aset, 'schedule_finish', None))
                except Exception:
                    pass

            ttype = (cdata.get("text_type") or "").lower()

            if ttype == "date":
                if cur_dt:
                    try:
                        cdata.body = cur_dt.strftime("%Y-%m-%d")
                    except Exception:
                        cdata.body = str(cur_dt).split("T")[0]

            elif ttype == "week":
                try:
                    if cur_dt and sch_start and sch_finish:
                        m = calculate_schedule_metrics(cur_dt, sch_start, sch_finish)
                        if m:
                            cdata.body = f"Week {m['week']}"
                except Exception:
                    pass

            elif ttype == "day_counter":
                try:
                    if cur_dt and sch_start and sch_finish:
                        m = calculate_schedule_metrics(cur_dt, sch_start, sch_finish)
                        if m:
                            cdata.body = f"Day {m['day']}"
                except Exception:
                    pass

            elif ttype == "progress":
                try:
                    if cur_dt and sch_start and sch_finish:
                        m = calculate_schedule_metrics(cur_dt, sch_start, sch_finish)
                        if m:
                            cdata.body = f"Progress: {m['progress']}%"
                    else:
                        percentage = int(round(1 + prog * 99))
                        cdata.body = f"Progress: {percentage}%"
                except Exception:
                    cdata.body = "Progress: --%"
    except Exception:
        pass

def _local_unregister_text_handler():
    global _LOCAL_TEXT_HANDLER
    try:

        if _LOCAL_TEXT_HANDLER and _LOCAL_TEXT_HANDLER in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(_LOCAL_TEXT_HANDLER)
    except Exception:
        pass

def _local_register_text_handler(settings=None):
    """Register fallback handler once, attach settings to known text objects if passed."""
    global _LOCAL_TEXT_HANDLER
    try:
        _local_unregister_text_handler()
    except Exception:
        pass
    try:

        coll = bpy.data.collections.get("Schedule_Display_Texts")
        if coll and settings is not None:
            for obj in list(coll.objects):
                _ensure_local_text_settings_on_obj(obj, settings)
    except Exception:
        pass
    _LOCAL_TEXT_HANDLER = _local_schedule_texts_update_handler
    try:
        if _LOCAL_TEXT_HANDLER not in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.append(_LOCAL_TEXT_HANDLER)
        # Immediate refresh
        _LOCAL_TEXT_HANDLER(bpy.context.scene, None)
    except Exception:
        pass

def _unified_register_text_handler(settings=None):
    ok = False
    try:
        if hasattr(tool.Sequence, "_register_multi_text_handler"):
            tool.Sequence._register_multi_text_handler(settings)
            ok = True
    except Exception:
        ok = False
    if not ok:
        _local_register_text_handler(settings)

def _infer_schedule_date_range(work_schedule):
    '''Infer earliest start and latest finish across tasks of the given work_schedule.'''
    try:
        import ifcopenshell
    except Exception:
        return None, None
    try:
        tasks = []
        try:
            if getattr(work_schedule, "Controls", None):
                for rel in work_schedule.Controls:
                    for ob in getattr(rel, "RelatedObjects", []) or []:
                        if hasattr(ob, "is_a") and ob.is_a("IfcTask"):
                            tasks.append(ob)
        except Exception:
            pass
        if not tasks:
            try:
                file = work_schedule.wrapped_data.file
                tasks = [t for t in file.by_type("IfcTask")]
            except Exception:
                tasks = []
        earliest = None
        latest = None
        for t in tasks:
            tt = getattr(t, "TaskTime", None) or getattr(t, "Time", None)
            if not tt:
                continue
            start_raw = None
            finish_raw = None
            for k in ("ActualStart","ScheduleStart","EarlyStart","LateStart","StartTime","Start"):
                if hasattr(tt, k) and getattr(tt, k):
                    start_raw = getattr(tt, k); break
            for k in ("ActualFinish","ScheduleFinish","EarlyFinish","LateFinish","FinishTime","Finish"):
                if hasattr(tt, k) and getattr(tt, k):
                    finish_raw = getattr(tt, k); break
            s = _parse_dt_any(start_raw)
            f = _parse_dt_any(finish_raw)
            if s:
                earliest = s if earliest is None else min(earliest, s)
            if f:
                latest = f if latest is None else max(latest, f)
        return earliest, latest
    except Exception:
        return None, None

from typing import get_args, TYPE_CHECKING, assert_never

# --- Lazy Enum items providers to avoid circular import with bonsai.tool ---

def _related_object_type_items(self, context):
    try:
        from typing import get_args
        from bonsai import tool as _tool
        vals = list(get_args(getattr(_tool.Sequence, "RELATED_OBJECT_TYPE", tuple()))) or []
    except Exception:
        vals = []
    if not vals:
        # Safe fallback
        vals = ("PRODUCT", "RESOURCE", "PROCESS")
    return [(str(v), str(v).replace("_", " ").title(), "") for v in vals]

# --- Helpers: clean task mappings when profiles or groups change ---
def _current_profile_names():
    try:
        props = tool.Sequence.get_animation_props()
        return [p.name for p in getattr(props, "profiles", [])]
    except Exception:
        return []

# ---- Unified Animation Bridges ----
def _sequence_has(attr: str) -> bool:
    try:
        return hasattr(tool.Sequence, attr)
    except Exception:
        return False

def _clear_previous_animation(context) -> None:
    """Unified function to clear all 4D animation data, including snapshots."""
    try:
        # Intenta usar la función más moderna y completa si está disponible
        if _sequence_has("clear_objects_animation"):
            # Llama con todos los flags a True para una limpieza total
            tool.Sequence.clear_objects_animation(
                include_blender_objects=True,
                clear_texts=True,
                clear_bars=True,
                clear_materials=True,
                reset_timeline=True,
                clear_keyframes=True,
                reset_colors=True, # Clave para resetear snapshots
            )
            return
    except Exception:
        pass

    # Fallback a un método más antiguo si existe
    try:
        if _sequence_has("clear_previous_animation"):
            tool.Sequence.clear_previous_animation(tool.Sequence)
            return
    except Exception:
        pass

    # Fallback final: limpieza manual y forzada
    for ob in list(bpy.data.objects):
        if ob.animation_data:
            ob.animation_data_clear()
        # Reset de propiedades para snapshots
        if hasattr(ob, 'hide_viewport'): ob.hide_viewport = False
        if hasattr(ob, 'hide_render'): ob.hide_render = False
        if hasattr(ob, 'color'): ob.color = (1.0, 1.0, 1.0, 1.0)

    # Limpieza de colecciones auxiliares
    for coll_name in ["Schedule_Display_Texts", "Bar Visual"]:
        if coll_name in bpy.data.collections:
            bpy.data.collections.remove(bpy.data.collections[coll_name])

def _get_animation_settings(context):
    try:
        if _sequence_has("get_animation_settings"):
            return tool.Sequence.get_animation_settings()
    except Exception:
        pass
    ws = tool.Sequence.get_work_schedule_props()
    ap = tool.Sequence.get_animation_props()
    return {
        "start": getattr(ws, "visualisation_start", None),
        "finish": getattr(ws, "visualisation_finish", None),
        "speed": getattr(ws, "visualisation_speed", 1.0),
        "profile_system": getattr(ap, "active_profile_system", "PROFILES"),
        "profile_stack": getattr(ap, "profile_stack", None),
    }

def _compute_product_frames(context, work_schedule, settings):
    if _sequence_has("get_product_frames_with_profiles"):
        return tool.Sequence.get_product_frames_with_profiles(work_schedule, settings)
    if _sequence_has("get_animation_product_frames_enhanced"):
        return tool.Sequence.get_animation_product_frames_enhanced(work_schedule, settings)
    if _sequence_has("get_animation_product_frames"):
        return tool.Sequence.get_animation_product_frames(work_schedule, settings)
    # As last resort, call core directly
    import bonsai.core.sequence as _core
    return _core.get_animation_product_frames(tool.Sequence, work_schedule, settings)

def _apply_profile_animation(context, product_frames, settings):
    if _sequence_has("apply_profile_animation"):
        tool.Sequence.apply_profile_animation(product_frames, settings); return
    if _sequence_has("animate_objects_with_profiles"):
        tool.Sequence.animate_objects_with_profiles(settings, product_frames); return
    if _sequence_has("animate_objects"):
        tool.Sequence.animate_objects(product_frames, settings); return
    import bonsai.core.sequence as _core
    _core.animate_objects(tool.Sequence, product_frames, settings)

def _ensure_default_group(context):
    # Ensure internal DEFAULT exists
    try:
        if UnifiedProfileManager is not None:
            UnifiedProfileManager.ensure_default_group(context)
    except Exception:
        pass
    # Ensure UI stack has at least one item (animation_group_stack or profile_stack)
    try:
        ap = tool.Sequence.get_animation_props()
        # Newer stack
        if hasattr(ap, "animation_group_stack") and len(ap.animation_group_stack) == 0:
            it = ap.animation_group_stack.add()
            it.group = getattr(ap, "profile_groups", "") or "DEFAULT"
            _safe_set(it, 'enabled', True)
        # Older stack
        if hasattr(ap, "profile_stack") and len(ap.profile_stack) == 0:
            it = ap.profile_stack.add()
            it.group = getattr(ap, "profile_groups", "") or "DEFAULT"
            _safe_set(it, 'enabled', True)
    except Exception:
        pass
def _clean_task_profile_mappings(context, removed_group_name: str | None = None):
    """
    Ensures per-task mapping stays consistent:
      - If a group is removed, drop its entry from each task.
      - If selected profile no longer exists in the current group, clear it.
    Also clears the visible Enum property if it points to a removed profile.
    """
    try:
        wprops = tool.Sequence.get_work_schedule_props()
        tprops = tool.Sequence.get_task_tree_props()
        anim = tool.Sequence.get_animation_props()
        active_group = getattr(anim, "profile_groups", "") or ""
        valid_names = set(_current_profile_names())

        for t in list(getattr(tprops, "tasks", [])):
            # Remove group-specific entry if group removed
            if removed_group_name and hasattr(t, "profile_group_choices"):
                to_keep = []
                for item in t.profile_group_choices:
                    if item.group_name != removed_group_name:
                        to_keep.append((item.group_name, getattr(item, 'enabled', False), getattr(item, 'selected_profile', "")))
                # Rebuild collection if anything changed
                if len(to_keep) != len(t.profile_group_choices):
                    t.profile_group_choices.clear()
                    for g, en, sel in to_keep:
                        it = t.profile_group_choices.add()
                        it.group_name = g
                        _safe_set(it, 'enabled', bool(en))
                        _safe_set(it, 'selected_profile', sel or "")

                # If the visible toggle points to removed group, turn it off
                if active_group == removed_group_name:
                    try:
                        t.use_active_profile_group = False
                        t.selected_profile_in_active_group = ""
                    except Exception:
                        pass

            # If current visible selection references a deleted profile, clear it
            try:
                if getattr(t, "selected_profile_in_active_group", "") and \
                   t.selected_profile_in_active_group not in valid_names:
                    t.selected_profile_in_active_group = ""
            except Exception:
                pass
            # Also clear stored selection for the active group
            try:
                if hasattr(t, "profile_group_choices") and active_group:
                    for item in t.profile_group_choices:
                        if item.group_name == active_group and getattr(item, 'selected_profile', "") not in valid_names:
                            _safe_set(item, 'selected_profile', "")
            except Exception:
                pass
    except Exception:
        # Best-effort; never break operator
        pass

class EnableStatusFilters(bpy.types.Operator):
    bl_idname = "bim.enable_status_filters"
    bl_label = "Enable Status Filters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_status_props()
        props.is_enabled = True
        hidden_statuses = {s.name for s in props.statuses if not s.is_visible}

        props.statuses.clear()

        statuses = set()
        for element in tool.Ifc.get().by_type("IfcPropertyEnumeratedValue"):
            if element.Name == "Status":
                if element.PartOfPset and isinstance(element.EnumerationValues, tuple):
                    pset = element.PartOfPset[0]
                    if pset.Name.startswith("Pset_") and pset.Name.endswith("Common"):
                        statuses.update(element.EnumerationValues)
                    elif pset.Name == "EPset_Status":  # Our secret sauce
                        statuses.update(element.EnumerationValues)
            elif element.Name == "UserDefinedStatus":
                statuses.add(element.NominalValue)

        statuses = ["No Status"] + sorted([s.wrappedValue for s in statuses])

        for status in statuses:
            new = props.statuses.add()
            new.name = status
            if new.name in hidden_statuses:
                new.is_visible = False

        visible_statuses = {s.name for s in props.statuses if s.is_visible}
        tool.Sequence.set_visibility_by_status(visible_statuses)
        return {"FINISHED"}

class DisableStatusFilters(bpy.types.Operator):
    bl_idname = "bim.disable_status_filters"
    bl_label = "Disable Status Filters"
    bl_description = "Deactivate status filters panel.\nCan be used to refresh the displayed statuses"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_status_props()

        all_statuses = {s.name for s in props.statuses}
        tool.Sequence.set_visibility_by_status(all_statuses)
        props.is_enabled = False
        return {"FINISHED"}

class ActivateStatusFilters(bpy.types.Operator):
    bl_idname = "bim.activate_status_filters"
    bl_label = "Activate Status Filters"
    bl_description = "Filter and display objects based on currently selected IFC statuses"
    bl_options = {"REGISTER", "UNDO"}

    only_if_enabled: bpy.props.BoolProperty(  # pyright: ignore[reportRedeclaration]
        name="Only If Filters are Enabled",
        description="Activate status filters only in case if they were enabled from the UI before.",
        default=False,
    )

    if TYPE_CHECKING:
        only_if_enabled: bool

    def execute(self, context):
        props = tool.Sequence.get_status_props()

        if not props.is_enabled:
            if not self.only_if_enabled:
                # Allow users to use the same operator to refresh filters,
                # even if they were not enabled before.
                # Typically would occur when operator is added to Quick Favorites.
                bpy.ops.bim.enable_status_filters()
            return {"FINISHED"}

        visible_statuses = {s.name for s in props.statuses if s.is_visible}
        tool.Sequence.set_visibility_by_status(visible_statuses)
        return {"FINISHED"}

class SelectStatusFilter(bpy.types.Operator):
    bl_idname = "bim.select_status_filter"
    bl_label = "Select Status Filter"
    bl_description = "Select elements with currently selected status"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()

    def execute(self, context):
        query = f"IfcProduct, /Pset_.*Common/.Status={self.name} + IfcProduct, EPset_Status.Status={self.name}"
        if self.name == "No Status":
            query = f"IfcProduct, /Pset_.*Common/.Status=NULL, EPset_Status.Status=NULL"
        for element in ifcopenshell.util.selector.filter_elements(tool.Ifc.get(), query):
            obj = tool.Ifc.get_object(element)
            if obj:
                obj.select_set(True)
        return {"FINISHED"}

class AddWorkPlan(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_work_plan"
    bl_label = "Add Work Plan"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        core.add_work_plan(tool.Ifc)

class EditWorkPlan(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_work_plan"
    bl_options = {"REGISTER", "UNDO"}
    bl_label = "Edit Work Plan"

    def _execute(self, context):
        props = tool.Sequence.get_work_plan_props()
        core.edit_work_plan(
            tool.Ifc,
            tool.Sequence,
            work_plan=tool.Ifc.get().by_id(props.active_work_plan_id),
        )

class RemoveWorkPlan(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_work_plan"
    bl_label = "Remove Work Plan"
    bl_options = {"REGISTER", "UNDO"}
    work_plan: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_work_plan(tool.Ifc, work_plan=tool.Ifc.get().by_id(self.work_plan))

class EnableEditingWorkPlan(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_plan"
    bl_label = "Enable Editing Work Plan"
    bl_options = {"REGISTER", "UNDO"}
    work_plan: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_plan(tool.Sequence, work_plan=tool.Ifc.get().by_id(self.work_plan))
        return {"FINISHED"}

class DisableEditingWorkPlan(bpy.types.Operator):
    bl_idname = "bim.disable_editing_work_plan"
    bl_options = {"REGISTER", "UNDO"}
    bl_label = "Disable Editing Work Plan"

    def execute(self, context):
        core.disable_editing_work_plan(tool.Sequence)
        return {"FINISHED"}

class EnableEditingWorkPlanSchedules(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_plan_schedules"
    bl_label = "Enable Editing Work Plan Schedules"
    bl_options = {"REGISTER", "UNDO"}
    work_plan: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_plan_schedules(tool.Sequence, work_plan=tool.Ifc.get().by_id(self.work_plan))
        return {"FINISHED"}

class AssignWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_work_schedule"
    bl_label = "Assign Work Schedule"
    bl_options = {"REGISTER", "UNDO"}
    work_plan: bpy.props.IntProperty()
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        core.assign_work_schedule(
            tool.Ifc,
            work_plan=tool.Ifc.get().by_id(self.work_plan),
            work_schedule=tool.Ifc.get().by_id(self.work_schedule),
        )

class UnassignWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_work_schedule"
    bl_label = "Unassign Work Schedule"
    bl_options = {"REGISTER", "UNDO"}
    work_plan: bpy.props.IntProperty()
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        core.unassign_work_schedule(
            tool.Ifc,
            work_schedule=tool.Ifc.get().by_id(self.work_schedule),
        )

class AddWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_work_schedule"
    bl_label = "Add Work Schedule"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()

    def _execute(self, context):
        core.add_work_schedule(tool.Ifc, tool.Sequence, name=self.name)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name", text="Name")
        self.props = tool.Sequence.get_work_schedule_props()
        layout.prop(self.props, "work_schedule_predefined_types", text="Type")
        if self.props.work_schedule_predefined_types == "USERDEFINED":
            layout.prop(self.props, "object_type", text="Object type")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class EditWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_work_schedule"
    bl_label = "Edit Work Schedule"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        core.edit_work_schedule(
            tool.Ifc,
            tool.Sequence,
            work_schedule=tool.Ifc.get().by_id(props.active_work_schedule_id),
        )

class RemoveWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_work_schedule"
    bl_label = "Remove Work Schedule"
    back_reference = "Remove provided work schedule."
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_work_schedule(tool.Ifc, work_schedule=tool.Ifc.get().by_id(self.work_schedule))

class CopyWorkSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.copy_work_schedule"
    bl_label = "Copy Work Schedule"
    bl_description = "Create a duplicate of the provided work schedule."
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()  # pyright: ignore[reportRedeclaration]

    if TYPE_CHECKING:
        work_schedule: int

    def _execute(self, context):
        core.copy_work_schedule(tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule))

class EnableEditingWorkSchedule(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_schedule"
    bl_label = "Enable Editing Work Schedule"
    bl_description = "Enable editing work schedule attributes."
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_schedule(tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule))
        return {"FINISHED"}

class EnableEditingWorkScheduleTasks(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_schedule_tasks"
    bl_label = "Enable Editing Work Schedule Tasks"
    bl_description = "Enable editing work scheduke tasks."
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule))
        return {"FINISHED"}

class LoadTaskProperties(bpy.types.Operator):
    bl_idname = "bim.load_task_properties"
    bl_label = "Load Task Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.load_task_properties(tool.Sequence)
        return {"FINISHED"}

class DisableEditingWorkSchedule(bpy.types.Operator):
    bl_idname = "bim.disable_editing_work_schedule"
    bl_label = "Disable Editing Work Schedule"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_work_schedule(tool.Sequence)
        return {"FINISHED"}

class AddTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_task"
    bl_label = "Add Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.add_task(tool.Ifc, tool.Sequence, parent_task=tool.Ifc.get().by_id(self.task))

class AddSummaryTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_summary_task"
    bl_label = "Add Task"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        core.add_summary_task(tool.Ifc, tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule))

class ExpandTask(bpy.types.Operator):
    bl_idname = "bim.expand_task"
    bl_label = "Expand Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def execute(self, context):
        core.expand_task(tool.Sequence, task=tool.Ifc.get().by_id(self.task))
        return {"FINISHED"}

class ContractTask(bpy.types.Operator):
    bl_idname = "bim.contract_task"
    bl_label = "Contract Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def execute(self, context):
        core.contract_task(tool.Sequence, task=tool.Ifc.get().by_id(self.task))
        return {"FINISHED"}

class RemoveTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_task"
    bl_label = "Remove Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_task(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class EnableEditingTaskTime(bpy.types.Operator, tool.Ifc.Operator):
    # IFC operator is needed because operator is adding a new task time to IFC
    # if it doesn't exist.
    bl_idname = "bim.enable_editing_task_time"
    bl_label = "Enable Editing Task Time"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.enable_editing_task_time(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class EditTaskTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_task_time"
    bl_label = "Edit Task Time"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        core.edit_task_time(
            tool.Ifc,
            tool.Sequence,
            tool.Resource,
            task_time=tool.Ifc.get().by_id(props.active_task_time_id),
        )

class EnableEditingTask(bpy.types.Operator):
    bl_idname = "bim.enable_editing_task_attributes"
    bl_label = "Enable Editing Task Attributes"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_task_attributes(tool.Sequence, task=tool.Ifc.get().by_id(self.task))
        return {"FINISHED"}

class DisableEditingTask(bpy.types.Operator):
    bl_idname = "bim.disable_editing_task"
    bl_label = "Disable Editing Task"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_task(tool.Sequence)
        return {"FINISHED"}

class EditTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_task"
    bl_label = "Edit Task"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        core.edit_task(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(props.active_task_id))

class CopyTaskAttribute(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.copy_task_attribute"
    bl_label = "Copy Task Attribute"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()

    def _execute(self, context):
        core.copy_task_attribute(tool.Ifc, tool.Sequence, attribute_name=self.name)

class CopyTaskCustomProfileGroup(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.copy_task_custom_profile_group"
    # UI may set these; declare to avoid attribute errors
    enabled: bpy.props.BoolProperty(name='Enabled', default=False, options={'HIDDEN'})
    group: bpy.props.StringProperty(name='Group', default='', options={'HIDDEN'})
    selected_profile: bpy.props.StringProperty(name='Selected Profile', default='', options={'HIDDEN'})

    bl_label = "Copy Task Custom Profile Group"
    bl_description = "Copy custom profile group configuration to selected tasks"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):

        try:
            # Obtener la tarea activa (fuente)
            tprops = tool.Sequence.get_task_tree_props()
            wprops = tool.Sequence.get_work_schedule_props()
            anim_props = tool.Sequence.get_animation_props()

            if not tprops.tasks or wprops.active_task_index >= len(tprops.tasks):
                self.report({'ERROR'}, "No active task to copy from")
                return {'CANCELLED'}

            source_task = tprops.tasks[wprops.active_task_index]

            # Obtener configuración de la tarea fuente
            source_group_selector = getattr(anim_props, "task_profile_group_selector", "")
            source_use_active = getattr(source_task, "use_active_profile_group", False)
            source_selected_profile = getattr(source_task, "selected_profile_in_active_group", "")

            # Obtener todas las asignaciones de grupos de la tarea fuente
            source_profile_choices = {}
            if hasattr(source_task, 'profile_group_choices'):
                for choice in source_task.profile_group_choices:
                    # Safe read with defaults in case attributes are missing
                    source_profile_choices[choice.group_name] = {
                        'enabled': getattr(choice, 'enabled', False),
                        'selected_profile': getattr(choice, 'selected_profile', "")
                    }
            # Contar tareas seleccionadas
            selected_tasks = [task for task in tprops.tasks if getattr(task, 'is_selected', False)]
            if not selected_tasks:
                self.report({'WARNING'}, "No tasks selected for copying. Please select target tasks first.")
                return {'CANCELLED'}

            # Aplicar a todas las tareas seleccionadas
            copied_count = 0
            for target_task in selected_tasks:
                if target_task.ifc_definition_id == source_task.ifc_definition_id:
                    continue  # Skip source task

                try:
                    # 1. Copiar configuración de grupo personalizado
                    target_task.use_active_profile_group = source_use_active
                    target_task.selected_profile_in_active_group = source_selected_profile

                    # 2. Copiar todas las asignaciones de grupos de perfiles
                    if hasattr(target_task, 'profile_group_choices'):
                        # Limpiar asignaciones existentes
                        target_task.profile_group_choices.clear()

                        # Copiar todas las asignaciones de la tarea fuente
                        for group_name, group_config in source_profile_choices.items():
                            new_choice = target_task.profile_group_choices.add()
                            new_choice.group_name = group_name
                            _safe_set(new_choice, 'enabled', group_config['enabled'])
                            _safe_set(new_choice, 'selected_profile', group_config['selected_profile'])

                    # 3. Sincronizar DEFAULT para la tarea destino
                    UnifiedProfileManager.sync_default_group_to_predefinedtype(context, target_task)

                    copied_count += 1

                except Exception as e:
                    print(f"Error copying to task {target_task.ifc_definition_id}: {e}")
                    continue

            if copied_count > 0:
                self.report({'INFO'}, f"Profile configuration copied to {copied_count} selected tasks")
            else:
                self.report({'WARNING'}, "No tasks were successfully updated")

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to copy profile configuration: {str(e)}")
            return {'CANCELLED'}
class AssignPredecessor(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_predecessor"
    bl_label = "Assign Predecessor"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.assign_predecessor(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class AssignSuccessor(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_successor"
    bl_label = "Assign Successor"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.assign_successor(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class UnassignPredecessor(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_predecessor"
    bl_label = "Unassign Predecessor"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.unassign_predecessor(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class UnassignSuccessor(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_successor"
    bl_label = "Unassign Successor"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.unassign_successor(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class AssignProduct(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_product"
    bl_label = "Assign Product"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()
    relating_product: bpy.props.IntProperty()

    def _execute(self, context):
        if self.relating_product:
            core.assign_products(
                tool.Ifc,
                tool.Sequence,
                tool.Spatial,
                task=tool.Ifc.get().by_id(self.task),
                products=[tool.Ifc.get().by_id(self.relating_product)],
            )
        else:
            core.assign_products(tool.Ifc, tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task))

        # Forzar el recálculo del conteo de outputs después de asignar.
        tool.Sequence.load_task_properties()
class UnassignProduct(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_product"
    bl_label = "Unassign Product"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()
    relating_product: bpy.props.IntProperty()

    def _execute(self, context):
        if self.relating_product:
            core.unassign_products(
                tool.Ifc,
                tool.Sequence,
                tool.Spatial,
                task=tool.Ifc.get().by_id(self.task),
                products=[tool.Ifc.get().by_id(self.relating_product)],
            )
        else:
            core.unassign_products(tool.Ifc, tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task))

        # Forzar el recálculo del conteo de outputs después de desasignar.
        tool.Sequence.load_task_properties()
class AssignProcess(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_process"
    bl_label = "Assign Process"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()
    related_object_type: bpy.props.EnumProperty(  # pyright: ignore [reportRedeclaration]
        items=_related_object_type_items,
    )
    related_object: bpy.props.IntProperty()

    if TYPE_CHECKING:
        related_object_type: tool.Sequence.RELATED_OBJECT_TYPE

    @classmethod
    def description(cls, context, properties):
        return f"Assign selected {properties.related_object_type} to the selected task"

    def _execute(self, context):
        if self.related_object_type == "RESOURCE":
            core.assign_resource(tool.Ifc, tool.Sequence, tool.Resource, task=tool.Ifc.get().by_id(self.task))
        elif self.related_object_type == "PRODUCT":
            if self.related_object:
                core.assign_input_products(
                    tool.Ifc,
                    tool.Sequence,
                    tool.Spatial,
                    task=tool.Ifc.get().by_id(self.task),
                    products=[tool.Ifc.get().by_id(self.related_object)],
                )
            else:
                core.assign_input_products(tool.Ifc, tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task))
        elif self.related_object_type == "CONTROL":
            self.report({"ERROR"}, "Assigning process control is not yet supported")  # TODO
        else:
            assert_never(self.related_object_type)

class UnassignProcess(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_process"
    bl_label = "Unassign Process"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()
    related_object_type: bpy.props.EnumProperty(  # pyright: ignore [reportRedeclaration]
        items=_related_object_type_items,
    )
    related_object: bpy.props.IntProperty()
    resource: bpy.props.IntProperty()

    if TYPE_CHECKING:
        related_object_type: tool.Sequence.RELATED_OBJECT_TYPE

    @classmethod
    def description(cls, context, properties):
        return f"Unassign selected {properties.related_object_type} from the selected task"

    def _execute(self, context):
        if self.related_object_type == "RESOURCE":
            core.unassign_resource(
                tool.Ifc,
                tool.Sequence,
                tool.Resource,
                task=tool.Ifc.get().by_id(self.task),
                resource=tool.Ifc.get().by_id(self.resource),
            )

        elif self.related_object_type == "PRODUCT":
            if self.related_object:
                core.unassign_input_products(
                    tool.Ifc,
                    tool.Sequence,
                    tool.Spatial,
                    task=tool.Ifc.get().by_id(self.task),
                    products=[tool.Ifc.get().by_id(self.related_object)],
                )
            else:
                core.unassign_input_products(
                    tool.Ifc, tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task)
                )
        elif self.related_object_type == "CONTROL":
            pass  # TODO
            self.report({"INFO"}, "Unassigning process control is not yet supported.")
        else:
            assert_never(self.related_object_type)
        return {"FINISHED"}

class GenerateGanttChart(bpy.types.Operator):
    bl_idname = "bim.generate_gantt_chart"
    bl_label = "Generate Gantt Chart"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def execute(self, context):
        try:
            work_schedule = tool.Ifc.get().by_id(self.work_schedule)
            if not work_schedule:
                self.report({'ERROR'}, "Work schedule not found")
                return {'CANCELLED'}
            import ifcopenshell.util.sequence as _useq
            if not _useq.get_root_tasks(work_schedule):
                self.report({'WARNING'}, "No tasks found in schedule")
                return {'CANCELLED'}
            core.generate_gantt_chart(tool.Sequence, work_schedule=work_schedule)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate Gantt chart: {str(e)}")
            return {'CANCELLED'}

class AddWorkCalendar(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_work_calendar"
    bl_label = "Add Work Calendar"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        core.add_work_calendar(tool.Ifc)

class EditWorkCalendar(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_work_calendar"
    bl_label = "Edit Work Calendar"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_calendar_props()
        core.edit_work_calendar(
            tool.Ifc,
            tool.Sequence,
            work_calendar=tool.Ifc.get().by_id(props.active_work_calendar_id),
        )

class RemoveWorkCalendar(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_work_calendar"
    bl_label = "Remove Work Plan"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_work_calendar(tool.Ifc, work_calendar=tool.Ifc.get().by_id(self.work_calendar))

class EnableEditingWorkCalendar(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_calendar"
    bl_label = "Enable Editing Work Calendar"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_calendar(tool.Sequence, work_calendar=tool.Ifc.get().by_id(self.work_calendar))
        return {"FINISHED"}

class DisableEditingWorkCalendar(bpy.types.Operator):
    bl_idname = "bim.disable_editing_work_calendar"
    bl_label = "Disable Editing Work Calendar"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_work_calendar(tool.Sequence)
        return {"FINISHED"}

class ImportWorkScheduleCSV(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_work_schedule_csv"
    bl_label = "Import Work Schedule CSV"
    bl_description = "Import work schedule from the provided .csv file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".csv"
    filter_glob: bpy.props.StringProperty(default="*.csv", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def _execute(self, context):
        from ifc4d.csv4d2ifc import Csv2Ifc

        self.file = tool.Ifc.get()
        start = time.time()
        csv2ifc = Csv2Ifc()
        csv2ifc.csv = self.filepath
        csv2ifc.file = self.file
        csv2ifc.execute()
        # === Ensure Start/Finish columns are visible after import ===
        try:
            import bonsai.core.sequence as core
            props = tool.Sequence.get_work_schedule_props()
            existing = {c.name for c in getattr(props, "columns", [])}
            # These map to headers "Start" and "Finish" in the UI
            if "IfcTaskTime.ScheduleStart" not in existing:
                core.add_task_column(tool.Sequence, "IfcTaskTime", "ScheduleStart", "string")
            if "IfcTaskTime.ScheduleFinish" not in existing:
                core.add_task_column(tool.Sequence, "IfcTaskTime", "ScheduleFinish", "string")
        except Exception as e:
            print("Auto-add Start/Finish columns after CSV import failed:", e)
        # Default sort by Identification ascending after import
        try:
            props = tool.Sequence.get_work_schedule_props()
            props.sort_column = "IfcTask.Identification"
            props.is_sort_reversed = False
            import bonsai.core.sequence as core
            core.load_task_tree(tool.Ifc, tool.Sequence)
        except Exception:
            pass
        self.report({"INFO"}, "Import finished in {:.2f} seconds".format(time.time() - start))

class SortWorkScheduleByIdAsc(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.sort_schedule_by_id_asc"
    bl_label = "Sort by ID (Ascending)"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        # Set sort column to Identification and ascending
        props.sort_column = "IfcTask.Identification"
        props.is_sort_reversed = False
        try:
            import bonsai.core.sequence as core
            core.load_task_tree(tool.Ifc, tool.Sequence)
        except Exception:
            pass
        return {"FINISHED"}

class ImportP6(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_p6"
    bl_label = "Import P6"
    bl_description = "Import provided .xml P6 file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def _execute(self, context):
        from ifc4d.p62ifc import P62Ifc

        self.file = tool.Ifc.get()
        start = time.time()
        p62ifc = P62Ifc()
        p62ifc.xml = self.filepath
        p62ifc.file = self.file
        p62ifc.work_plan = self.file.by_type("IfcWorkPlan")[0] if self.file.by_type("IfcWorkPlan") else None
        p62ifc.execute()
        self.report({"INFO"}, "Import finished in {:.2f} seconds".format(time.time() - start))

class ImportP6XER(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_p6xer"
    bl_label = "Import P6 XER"
    bl_description = "Import provided .xer P6 file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xer"
    filter_glob: bpy.props.StringProperty(default="*.xer", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def _execute(self, context):
        from ifc4d.p6xer2ifc import P6XER2Ifc

        self.file = tool.Ifc.get()
        start = time.time()
        p6xer2ifc = P6XER2Ifc()
        p6xer2ifc.xer = self.filepath
        p6xer2ifc.file = self.file
        p6xer2ifc.work_plan = self.file.by_type("IfcWorkPlan")[0] if self.file.by_type("IfcWorkPlan") else None
        p6xer2ifc.execute()
        self.report({"INFO"}, "Import finished in {:.2f} seconds".format(time.time() - start))

class ImportPP(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_pp"
    bl_label = "Import Powerproject .pp"
    bl_description = "Import provided .pp file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".pp"
    filter_glob: bpy.props.StringProperty(default="*.pp", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def _execute(self, context):
        from ifc4d.pp2ifc import PP2Ifc

        self.file = tool.Ifc.get()
        start = time.time()
        pp2ifc = PP2Ifc()
        pp2ifc.pp = self.filepath
        pp2ifc.file = self.file
        pp2ifc.work_plan = self.file.by_type("IfcWorkPlan")[0] if self.file.by_type("IfcWorkPlan") else None
        pp2ifc.execute()
        self.report({"INFO"}, "Import finished in {:.2f} seconds".format(time.time() - start))

class ImportMSP(bpy.types.Operator, tool.Ifc.Operator, ImportHelper):
    bl_idname = "bim.import_msp"
    bl_label = "Import MSP"
    bl_description = "Import provided .xml MSP file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def _execute(self, context):
        from ifc4d.msp2ifc import MSP2Ifc

        self.file = tool.Ifc.get()
        start = time.time()
        msp2ifc = MSP2Ifc()
        msp2ifc.xml = self.filepath
        msp2ifc.file = self.file
        msp2ifc.work_plan = self.file.by_type("IfcWorkPlan")[0] if self.file.by_type("IfcWorkPlan") else None
        msp2ifc.execute()
        self.report({"INFO"}, "Import finished in {:.2f} seconds".format(time.time() - start))

class ExportMSP(bpy.types.Operator, ExportHelper):
    bl_idname = "bim.export_msp"
    bl_label = "Export MSP"
    bl_description = "Export work schedule as .xml MSP file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})
    holiday_start_date: bpy.props.StringProperty(default="2022-01-01", name="Holiday Start Date")
    holiday_finish_date: bpy.props.StringProperty(default="2023-01-01", name="Holiday Finish Date")

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def execute(self, context):
        from ifc4d.ifc2msp import Ifc2Msp

        self.file = tool.Ifc.get()
        start = time.time()
        ifc2msp = Ifc2Msp()
        ifc2msp.work_schedule = self.file.by_type("IfcWorkSchedule")[0]
        ifc2msp.xml = bpy.path.ensure_ext(self.filepath, ".xml")
        ifc2msp.file = self.file
        ifc2msp.holiday_start_date = parser.parse(self.holiday_start_date).date()
        ifc2msp.holiday_finish_date = parser.parse(self.holiday_finish_date).date()
        ifc2msp.execute()
        self.report({"INFO"}, "Export finished in {:.2f} seconds".format(time.time() - start))
        return {"FINISHED"}

class ExportP6(bpy.types.Operator, ExportHelper):
    bl_idname = "bim.export_p6"
    bl_label = "Export P6"
    bl_description = "Export work schedule as .xml P6 file."
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xml"
    filter_glob: bpy.props.StringProperty(default="*.xml", options={"HIDDEN"})
    holiday_start_date: bpy.props.StringProperty(default="2022-01-01", name="Holiday Start Date")
    holiday_finish_date: bpy.props.StringProperty(default="2023-01-01", name="Holiday Finish Date")

    @classmethod
    def poll(cls, context):
        ifc_file = tool.Ifc.get()
        if ifc_file is None:
            cls.poll_message_set("No IFC file is loaded.")
            return False
        return True

    def execute(self, context):
        from ifc4d.ifc2p6 import Ifc2P6

        self.file = tool.Ifc.get()
        start = time.time()
        ifc2p6 = Ifc2P6()
        ifc2p6.xml = bpy.path.ensure_ext(self.filepath, ".xml")
        ifc2p6.file = self.file
        ifc2p6.holiday_start_date = parser.parse(self.holiday_start_date).date()
        ifc2p6.holiday_finish_date = parser.parse(self.holiday_finish_date).date()
        ifc2p6.execute()
        self.report({"INFO"}, "Export finished in {:.2f} seconds".format(time.time() - start))
        return {"FINISHED"}

class EnableEditingWorkCalendarTimes(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_calendar_times"
    bl_label = "Enable Editing Work Calendar Times"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_calendar_times(tool.Sequence, work_calendar=tool.Ifc.get().by_id(self.work_calendar))
        return {"FINISHED"}

class AddWorkTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_work_time"
    bl_label = "Add Work Time"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()
    time_type: bpy.props.StringProperty()

    def _execute(self, context):
        core.add_work_time(tool.Ifc, work_calendar=tool.Ifc.get().by_id(self.work_calendar), time_type=self.time_type)

class EnableEditingWorkTime(bpy.types.Operator):
    bl_idname = "bim.enable_editing_work_time"
    bl_label = "Enable Editing Work Time"
    bl_options = {"REGISTER", "UNDO"}
    work_time: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_work_time(tool.Sequence, work_time=tool.Ifc.get().by_id(self.work_time))
        return {"FINISHED"}

class DisableEditingWorkTime(bpy.types.Operator):
    bl_idname = "bim.disable_editing_work_time"
    bl_label = "Disable Editing Work Time"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_work_time(tool.Sequence)
        return {"FINISHED"}

class EditWorkTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_work_time"
    bl_label = "Edit Work Time"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        core.edit_work_time(tool.Ifc, tool.Sequence)

class RemoveWorkTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_work_time"
    bl_label = "Remove Work Plan"
    bl_options = {"REGISTER", "UNDO"}
    work_time: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_work_time(tool.Ifc, work_time=tool.Ifc.get().by_id(self.work_time))
        return {"FINISHED"}

class AssignRecurrencePattern(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_recurrence_pattern"
    bl_label = "Assign Recurrence Pattern"
    bl_options = {"REGISTER", "UNDO"}
    work_time: bpy.props.IntProperty()
    recurrence_type: bpy.props.StringProperty()

    def _execute(self, context):
        core.assign_recurrence_pattern(
            tool.Ifc, work_time=tool.Ifc.get().by_id(self.work_time), recurrence_type=self.recurrence_type
        )
        return {"FINISHED"}

class UnassignRecurrencePattern(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_recurrence_pattern"
    bl_label = "Unassign Recurrence Pattern"
    bl_options = {"REGISTER", "UNDO"}
    recurrence_pattern: bpy.props.IntProperty()

    def _execute(self, context):
        core.unassign_recurrence_pattern(tool.Ifc, recurrence_pattern=tool.Ifc.get().by_id(self.recurrence_pattern))
        return {"FINISHED"}

class AddTimePeriod(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.add_time_period"
    bl_label = "Add Time Period"
    bl_options = {"REGISTER", "UNDO"}
    recurrence_pattern: bpy.props.IntProperty()

    def _execute(self, context):
        core.add_time_period(tool.Ifc, tool.Sequence, recurrence_pattern=tool.Ifc.get().by_id(self.recurrence_pattern))

class RemoveTimePeriod(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_time_period"
    bl_label = "Remove Time Period"
    bl_options = {"REGISTER", "UNDO"}
    time_period: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_time_period(tool.Ifc, time_period=tool.Ifc.get().by_id(self.time_period))

class EnableEditingTaskCalendar(bpy.types.Operator):
    bl_idname = "bim.enable_editing_task_calendar"
    bl_label = "Enable Editing Task Calendar"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_task_calendar(tool.Sequence, task=tool.Ifc.get().by_id(self.task))
        return {"FINISHED"}

class EditTaskCalendar(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_task_calendar"
    bl_label = "Edit Task Calendar"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.edit_task_calendar(
            tool.Ifc,
            tool.Sequence,
            task=tool.Ifc.get().by_id(self.task),
            work_calendar=tool.Ifc.get().by_id(self.work_calendar),
        )

class RemoveTaskCalendar(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.remove_task_calendar"
    bl_label = "Remove Task Calendar"
    bl_options = {"REGISTER", "UNDO"}
    work_calendar: bpy.props.IntProperty()
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.remove_task_calendar(
            tool.Ifc,
            tool.Sequence,
            task=tool.Ifc.get().by_id(self.task),
            work_calendar=tool.Ifc.get().by_id(self.work_calendar),
        )

class EnableEditingTaskSequence(bpy.types.Operator):
    bl_idname = "bim.enable_editing_task_sequence"
    bl_label = "Enable Editing Task Sequence"
    task: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_task_sequence(tool.Sequence)
        return {"FINISHED"}

class DisableEditingTaskTime(bpy.types.Operator):
    bl_idname = "bim.disable_editing_task_time"
    bl_label = "Disable Editing Task Time"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_task_time(tool.Sequence)
        return {"FINISHED"}

class EnableEditingSequenceAttributes(bpy.types.Operator):
    bl_idname = "bim.enable_editing_sequence_attributes"
    bl_label = "Enable Editing Sequence Attributes"
    bl_options = {"REGISTER", "UNDO"}
    sequence: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_sequence_attributes(tool.Sequence, rel_sequence=tool.Ifc.get().by_id(self.sequence))
        return {"FINISHED"}

class EnableEditingSequenceTimeLag(bpy.types.Operator):
    bl_idname = "bim.enable_editing_sequence_lag_time"
    bl_label = "Enable Editing Sequence Time Lag"
    bl_options = {"REGISTER", "UNDO"}
    sequence: bpy.props.IntProperty()
    lag_time: bpy.props.IntProperty()

    def execute(self, context):
        core.enable_editing_sequence_lag_time(
            tool.Sequence,
            rel_sequence=tool.Ifc.get().by_id(self.sequence),
            lag_time=tool.Ifc.get().by_id(self.lag_time),
        )
        return {"FINISHED"}

class UnassignLagTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.unassign_lag_time"
    bl_label = "Unassign Time Lag"
    bl_options = {"REGISTER", "UNDO"}
    sequence: bpy.props.IntProperty()

    def _execute(self, context):
        core.unassign_lag_time(tool.Ifc, tool.Sequence, rel_sequence=tool.Ifc.get().by_id(self.sequence))

class AssignLagTime(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.assign_lag_time"
    bl_label = "Assign Time Lag"
    bl_options = {"REGISTER", "UNDO"}
    sequence: bpy.props.IntProperty()

    def _execute(self, context):
        core.assign_lag_time(tool.Ifc, rel_sequence=tool.Ifc.get().by_id(self.sequence))

class EditSequenceAttributes(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_sequence_attributes"
    bl_label = "Edit Sequence"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        core.edit_sequence_attributes(
            tool.Ifc,
            tool.Sequence,
            rel_sequence=tool.Ifc.get().by_id(props.active_sequence_id),
        )

class EditSequenceTimeLag(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.edit_sequence_lag_time"
    bl_label = "Edit Time Lag"
    bl_options = {"REGISTER", "UNDO"}
    lag_time: bpy.props.IntProperty()

    def _execute(self, context):
        core.edit_sequence_lag_time(tool.Ifc, tool.Sequence, lag_time=tool.Ifc.get().by_id(self.lag_time))

class DisableEditingSequence(bpy.types.Operator):
    bl_idname = "bim.disable_editing_sequence"
    bl_label = "Disable Editing Sequence"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.disable_editing_rel_sequence(tool.Sequence)
        return {"FINISHED"}

class SelectTaskRelatedProducts(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.select_task_related_products"
    bl_label = "Select All Output Products"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.select_task_outputs(tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task))

class SelectTaskRelatedInputs(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.select_task_related_inputs"
    bl_label = "Select All Input Products"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.select_task_inputs(tool.Sequence, tool.Spatial, task=tool.Ifc.get().by_id(self.task))

class VisualiseWorkScheduleDate(bpy.types.Operator):
    bl_idname = "bim.visualise_work_schedule_date"
    bl_label = "Visualise Work Schedule Date"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    @classmethod
    def poll(cls, context):
        props = tool.Sequence.get_work_schedule_props()
        return bool(props.visualisation_start)

    def execute(self, context):
        # --- INICIO DE LA CORRECCIÓN ---
        # 1. FORZAR LA SINCRONIZACIÓN: Al igual que con la animación, esto asegura
        #    que el snapshot use los datos más actualizados del grupo que se está editando.
        try:
            tool.Sequence.sync_active_group_to_json()
        except Exception as e:
            print(f"Error syncing profiles for snapshot: {e}")
        # --- FIN DE LA CORRECCIÓN ---

        # Obtener el work schedule
        work_schedule = tool.Ifc.get().by_id(self.work_schedule)

        # NUEVA CORRECCIÓN: Obtener el rango de visualización configurado
        viz_start, viz_finish = tool.Sequence.get_visualization_date_range()

        if not viz_start:
            self.report({'ERROR'}, "No start date configured for visualization")
            return {'CANCELLED'}

        # CORRECCIÓN: Usar la fecha de inicio de visualización como fecha del snapshot
        snapshot_date = viz_start

        # Ejecutar la lógica central de visualización CON el rango de visualización
        product_states = tool.Sequence.process_construction_state(
            work_schedule,
            snapshot_date,
            viz_start=viz_start,
            viz_finish=viz_finish  # NUEVO: Pasar el rango de visualización
        )

        # Aplicar el snapshot con los estados corregidos
        tool.Sequence.show_snapshot(product_states)

        # Dar feedback claro al usuario sobre qué grupo se usó
        anim_props = tool.Sequence.get_animation_props()
        active_group = None
        for stack_item in anim_props.animation_group_stack:
            if getattr(stack_item, 'enabled', False) and stack_item.group:
                active_group = stack_item.group
                break

        group_used = active_group or "DEFAULT"

        # NUEVO: Información adicional sobre el filtrado
        viz_end_str = viz_finish.strftime('%Y-%m-%d') if viz_finish else "No limit"
        self.report({'INFO'}, f"Snapshot at {snapshot_date.strftime('%Y-%m-%d')} using group '{group_used}' (range: {viz_start.strftime('%Y-%m-%d')} to {viz_end_str})")

        return {"FINISHED"}

class GuessDateRange(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.guess_date_range"
    bl_label = "Guess Work Schedule Date Range"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        # Try core implementation first
        start_date = finish_date = None
        try:
            result = core.guess_date_range(tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule))
            if result:
                try:
                    start_date, finish_date = result
                except Exception:
                    start_date = finish_date = None
        except Exception:
            start_date = finish_date = None
        if not (start_date and finish_date):
            try:
                task_props = tool.Sequence.get_task_tree_props()
                starts, finishes = [], []
                from dateutil import parser as _parser
                for t in task_props.tasks:
                    s = getattr(t, "start", "") or getattr(t, "derived_start", "")
                    f = getattr(t, "finish", "") or getattr(t, "derived_finish", "")
                    if s and s not in ("-", ""):
                        try:
                            starts.append(_parser.parse(str(s), dayfirst=True, fuzzy=True))
                        except Exception:
                            pass
                    if f and f not in ("-", ""):
                        try:
                            finishes.append(_parser.parse(str(f), dayfirst=True, fuzzy=True))
                        except Exception:
                            pass
                if starts and finishes:
                    start_date = min(starts)
                    finish_date = max(finishes)
            except Exception:
                pass

        # Apply to Animation Settings
        try:
            tool.Sequence.update_visualisation_date(start_date, finish_date)
        except Exception:
            pass

        # Force UI refresh
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'PROPERTIES':
                        area.tag_redraw()
        except Exception:
            pass
        return {"FINISHED"}

class VisualiseWorkScheduleDateRange(bpy.types.Operator):
    bl_idname = "bim.visualise_work_schedule_date_range"
    bl_label = "Create / Update 4D Animation" # Texto actualizado para la UI
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    # NUEVO: Propiedad para que el usuario elija la acción en el diálogo emergente
    camera_action: bpy.props.EnumProperty(
        name="Camera Action",
        description="Choose whether to create a new camera or update the existing one",
        items=[
            ('UPDATE', "Update Existing Camera", "Update the existing 4D camera with current settings"),
            ('CREATE_NEW', "Create New Camera", "Create a new 4D camera"),
            ('NONE', "No Camera Action", "Do not add or modify the camera"),
        ],
        default='UPDATE'
    )

    @classmethod
    def poll(cls, context):
        props = tool.Sequence.get_work_schedule_props()
        has_start = bool(props.visualisation_start and props.visualisation_start != "-")
        has_finish = bool(props.visualisation_finish and props.visualisation_finish != "-")
        return has_start and has_finish

    def execute(self, context):
        try:
            # --- 1. Lógica de animación de productos (sin cambios) ---
            tool.Sequence.sync_active_group_to_json()
            work_schedule = tool.Ifc.get().by_id(self.work_schedule)
            settings = tool.Sequence.get_animation_settings()
            if not work_schedule or not settings:
                self.report({'ERROR'}, "Work schedule or animation settings are invalid.")
                return {'CANCELLED'}

            _clear_previous_animation(context)

            product_frames = tool.Sequence.get_animation_product_frames_enhanced(work_schedule, settings)
            if not product_frames:
                self.report({'WARNING'}, "No products found to animate.")

            tool.Sequence.animate_objects_with_profiles(settings, product_frames)
            tool.Sequence.add_text_animation_handler(settings)
            tool.Sequence.set_object_shading()
            bpy.context.scene.frame_start = settings["start_frame"]
            bpy.context.scene.frame_end = int(settings["start_frame"] + settings["total_frames"])

            # --- 2. LÓGICA DE CÁMARA CORREGIDA ---
            # --- 2. LÓGICA DE CÁMARA CORREGIDA ---
            if self.camera_action != 'NONE':
                existing_cam = next((obj for obj in bpy.data.objects if "4D_Animation_Camera" in obj.name), None)

                if self.camera_action == 'UPDATE':
                    if existing_cam:
                        self.report({'INFO'}, f"Updating existing camera: {existing_cam.name}")
                        # CORRECCIÓN: Llamar a la función solo con el objeto cámara.
                        tool.Sequence.update_animation_camera(existing_cam)
                    else:
                        self.report({'INFO'}, "No existing camera to update. Creating a new one instead.")
                        # CORRECCIÓN: Llamar a la función sin argumentos.
                        tool.Sequence.add_animation_camera()
                elif self.camera_action == 'CREATE_NEW':
                    self.report({'INFO'}, "Creating a new 4D camera.")
                    # CORRECCIÓN: Llamar a la función sin argumentos.
                    tool.Sequence.add_animation_camera()

                        # --- CONFIGURACIÓN AUTOMÁTICA DEL HUD (Sistema Dual) ---
            try:
                if settings and settings.get("start") and settings.get("finish"):
                    print("🎬 Auto-configuring HUD Compositor for high-quality renders...")
                    bpy.ops.bim.setup_hud_compositor()
                    print("✅ HUD Compositor auto-configured successfully")
                    print("📹 Regular renders (Ctrl+F12) will now include HUD overlay")
                else: # Fallback al HUD de Viewport si no hay timeline
                    bpy.ops.bim.enable_schedule_hud()
            except Exception as e:
                print(f"⚠️ Auto-setup of HUD failed: {e}. Falling back to Viewport HUD.")
                try:
                    bpy.ops.bim.enable_schedule_hud()
                except Exception:
                    pass
            
            # <-- INICIO DE LA CORRECCIÓN DE VISIBILIDAD DE TEXTOS 3D -->
            try:
                anim_props = tool.Sequence.get_animation_props()
                camera_props = anim_props.camera_orbit
                collection = bpy.data.collections.get("Schedule_Display_Texts")
                
                if collection:
                    # Sincroniza la visibilidad de la colección con el estado del checkbox.
                    # Si show_3d_schedule_texts es False, hide_viewport debe ser True.
                    should_hide = not getattr(camera_props, "show_3d_schedule_texts", False)
                    collection.hide_viewport = should_hide
                    collection.hide_render = should_hide
                    
                    # Forzar redibujado de la vista 3D para que el cambio sea inmediato.
                    for window in context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == 'VIEW_3D':
                                area.tag_redraw()
            except Exception as e:
                print(f"⚠️ Could not sync 3D text visibility: {e}")
            # <-- FIN DE LA CORRECCIÓN -->

            self.report({'INFO'}, f"Animation created successfully for {len(product_frames)} products.")
            return {'FINISHED'}

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Animation failed: {str(e)}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        # CORRECCIÓN: La búsqueda de la cámara es más robusta.
        existing_cam = next((obj for obj in bpy.data.objects if "4D_Animation_Camera" in obj.name), None)

        if existing_cam:
            # Si encuentra una cámara, muestra el diálogo de confirmación.
            return context.window_manager.invoke_props_dialog(self)
        else:
            # Si no, la acción por defecto es crear una nueva y ejecutar directamente.
            self.camera_action = 'CREATE_NEW'
            return self.execute(context)

    def draw(self, context):
        # Dibuja las opciones en el diálogo emergente.
        layout = self.layout
        layout.label(text="An existing 4D camera was found.")
        layout.label(text="What would you like to do with the camera?")
        layout.prop(self, "camera_action", expand=True)

class CreateAnimation(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.create_animation"
    bl_label = "Create 4D Animation"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        anim_props = tool.Sequence.get_animation_props()

        # Basic validation
        start = getattr(props, "visualisation_start", None)
        finish = getattr(props, "visualisation_finish", None)
        if not start or not finish or "-" in (start, finish):
            self.report({'ERROR'}, "Invalid date range. Set Start and Finish in Animation Settings.")
            return {'CANCELLED'}

        # Ensure default group & stack
        _ensure_default_group(context)

        # Clear previous
        _clear_previous_animation(context)

        # Resolve work schedule
        ws_id = getattr(props, "active_work_schedule_id", None)
        if not ws_id:
            self.report({'ERROR'}, "No active Work Schedule selected.")
            return {'CANCELLED'}
        work_schedule = tool.Ifc.get().by_id(ws_id)
        if not work_schedule:
            self.report({'ERROR'}, "Active Work Schedule not found in IFC.")
            return {'CANCELLED'}

        # Settings
        settings = _get_animation_settings(context)

        # Compute frames
        try:
            frames = _compute_product_frames(context, work_schedule, settings)
        except Exception as e:
            self.report({'ERROR'}, f"Frame computation failed: {e}")
            return {'CANCELLED'}

        # Apply
        try:
            _apply_profile_animation(context, frames, settings)
        except Exception as e:
            self.report({'ERROR'}, f"Animation apply failed: {e}")
            return {'CANCELLED'}

        # --- Camera/Orbit: create/animate camera if configured ---
        try:
            _anim_props = tool.Sequence.get_animation_props()
            _cam_props = getattr(_anim_props, "camera_orbit", None)
            if _cam_props and getattr(_cam_props, "orbit_mode", "NONE") != "NONE":
                tool.Sequence.add_animation_camera()
        except Exception as _cam_e:
            # Non-fatal: object animation should not fail because camera failed
            self.report({'WARNING'}, f"Camera creation skipped: {_cam_e}")

        self.report({'INFO'}, f"Animation created for {len(frames)} elements")
        return {'FINISHED'}

    def execute(self, context):
        try:
            return self._execute(context)
        except Exception as e:
            self.report({'ERROR'}, f"Unexpected error: {e}")
            return {'CANCELLED'}

class ClearAnimation(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.clear_animation"
    bl_label = "Clear 4D Animation"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        _clear_previous_animation(context)
        self.report({'INFO'}, "Previous animation cleared")
        return {'FINISHED'}

    def execute(self, context):
        try:
            return self._execute(context)
        except Exception as e:
            self.report({'ERROR'}, f"Unexpected error: {e}")
            return {'CANCELLED'}

class SnapshotWithProfiles(tool.Ifc.Operator, bpy.types.Operator):
    bl_idname = "bim.snapshot_with_profiles"
    bl_label = "Snapshot (Profiles)"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        # Ensure default group and gather props
        try:
            UnifiedProfileManager.ensure_default_group(context)
        except Exception:
            pass

        ws_props = tool.Sequence.get_work_schedule_props()
        anim_props = tool.Sequence.get_animation_props()

        # Resolve work schedule
        ws_id = getattr(ws_props, "active_work_schedule_id", None)
        if not ws_id:
            self.report({'ERROR'}, "No active Work Schedule selected.")
            return {'CANCELLED'}
        work_schedule = tool.Ifc.get().by_id(ws_id)
        if not work_schedule:
            self.report({'ERROR'}, "Active Work Schedule not found in IFC.")
            return {'CANCELLED'}

        # Settings & current frame
        settings = _get_animation_settings(context)
        cur_frame = int(bpy.context.scene.frame_current) if hasattr(bpy.context.scene, "frame_current") else int(settings.get("start_frame", 1))

        # Compute frames per product
        try:
            product_frames = _compute_product_frames(context, work_schedule, settings)
        except Exception as e:
            self.report({'ERROR'}, f"Computing frames failed: {e}")
            return {'CANCELLED'}

        # Determine snapshot group
        try:
            # Prefer Animation Stack (first enabled item)
            snap_group = None
            if hasattr(anim_props, 'animation_group_stack'):
                for it in anim_props.animation_group_stack:
                    if getattr(it, 'enabled', False) and getattr(it, 'group', None):
                        snap_group = it.group
                        break
            # Fallback to UI-selected group
            if not snap_group:
                snap_group = getattr(anim_props, 'profile_groups', None)
            # Final fallback
            if not snap_group:
                snap_group = 'DEFAULT'
            print(f"📸 Snapshot uses profile group: '{snap_group}'")
            try:
                if snap_group == getattr(anim_props, 'profile_groups', None):
                    tool.Sequence.sync_active_group_to_json()
            except Exception:
                pass
        except Exception:
            snap_group = 'DEFAULT'

        # Cache original colors
        original_colors = {}
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                original_colors[obj.name] = list(obj.color)

        # Apply state color without keyframes
        applied = 0
        for obj in bpy.data.objects:
            element = tool.Ifc.get_entity(obj)
            if not element:
                continue
            if hasattr(element, "is_a") and element.is_a("IfcSpace"):
                try:
                    obj.hide_viewport = True
                    obj.hide_render = True
                except Exception:
                    pass
                continue
            pid = element.id() if hasattr(element, "id") else None
            if pid is None or pid not in product_frames:
                continue

            original_color = original_colors.get(obj.name, [1.0, 1.0, 1.0, 1.0])
            frames_list = product_frames[pid]
            # choose the frame_data whose interval covers current frame; fallback to closest
            frame_data = None
            for fd in frames_list:
                st = fd.get("states", {}).get("active", (0, -1))
                if st[0] <= cur_frame <= st[1]:
                    frame_data = fd; break
            if frame_data is None:
                # Check before_start then after_end
                for key in ("before_start", "after_end"):
                    st = frames_list[0].get("states", {}).get(key, (0, -1))
                    if st[0] <= cur_frame <= st[1]:
                        frame_data = frames_list[0]; break
            if frame_data is None:
                frame_data = frames_list[0]

            # Resolve a profile by task assignment first; else by group+predefined; else generic
            task = frame_data.get("task") or tool.Ifc.get().by_id(frame_data.get("task_id"))
            profile = None
            try:
                profile = tool.Sequence.get_assigned_profile_for_task(task, anim_props, snap_group)
            except Exception:
                pass
            if not profile:
                try:
                    predefined_type = (task.PredefinedType if task else None) or "NOTDEFINED"
                except Exception:
                    predefined_type = "NOTDEFINED"
                try:
                    profile = tool.Sequence.load_profile_from_group(snap_group, predefined_type)
                except Exception:
                    profile = None
                if not profile:
                    profile = tool.Sequence.create_generic_profile(predefined_type)

            # Derive state at current frame
            state = "end"
            st_map = frame_data.get("states", {})
            if "before_start" in st_map and st_map["before_start"][0] <= cur_frame <= st_map["before_start"][1]:
                state = "start"
            elif "active" in st_map and st_map["active"][0] <= cur_frame <= st_map["active"][1]:
                state = "in_progress"
            else:
                state = "end"

            # Apply instantly (no keyframes)
            try:
                if state == "start" and getattr(profile, "consider_start", True) is False:
                    # Hide pre-start outputs; inputs remain visible by default
                    if frame_data.get("relationship") == "output":
                        obj.hide_viewport = True
                        obj.hide_render = True
                    applied += 1
                    continue
                if state == "in_progress" and getattr(profile, "consider_active", True) is False:
                    applied += 1
                    continue
                if state == "end" and getattr(profile, "consider_end", True) is False:
                    applied += 1
                    continue

                # choose color
                if state == "start":
                    col = getattr(profile, "start_color", [1,1,1,1])
                elif state == "in_progress":
                    col = getattr(profile, "in_progress_color", [0,1,0,1])
                else:  # end
                    if getattr(profile, "use_end_original_color", False):
                        col = original_color
                    else:
                        col = getattr(profile, "end_color", [0.7,0.7,0.7,1])

                obj.color = col
                try:
                    if state in ('active','in_progress'):
                        prog = None
                        try:
                            prog = _seq_data.compute_progress_at_frame(task, cur_frame, settings) if task else None
                        except Exception:
                            # Fallback: usar estados del frame_data
                            st = frame_data.get('states', {}).get('active', (cur_frame, cur_frame+1))
                            if st[1] > st[0]:
                                prog = (cur_frame - st[0]) / max(1, (st[1] - st[0]))
                        vals = _seq_data.interpolate_profile_values(profile, 'in_progress', max(0.0, min(1.0, prog if prog is not None else 1.0)))
                        a = vals.get('alpha')
                        if a is not None:
                            c = list(obj.color)
                            if len(c) < 4:
                                c = [c[0], c[1], c[2], 1.0]
                            c[3] = float(a)
                            obj.color = c
                except Exception:
                    pass
                obj.hide_viewport = False
                obj.hide_render = False
                applied += 1
            except Exception:
                pass

        # Ensure object color shading
        try:
            area = tool.Blender.get_view3d_area()
            area.spaces[0].shading.color_type = "OBJECT"
        except Exception:
            pass

        self.report({'INFO'}, f"Snapshot applied to {applied} objects using group '{snap_group}' at frame {cur_frame}")
        return {'FINISHED'}

    def execute(self, context):
        try:
            return self._execute(context)
        except Exception as e:
            self.report({'ERROR'}, f"Unexpected error: {e}")
            return {'CANCELLED'}

class Bonsai_DatePicker(bpy.types.Operator):
    bl_label = "Date Picker"
    bl_idname = "bim.datepicker"
    bl_options = {"REGISTER", "UNDO"}
    target_prop: bpy.props.StringProperty(name="Target date prop to set")
    # TODO: base it on property type.
    include_time: bpy.props.BoolProperty(name="Include Time", default=True)

    if TYPE_CHECKING:
        target_prop: str
        include_time: bool

    def execute(self, context):
        selected_date = context.scene.DatePickerProperties.selected_date
        try:
            # Just to make sure the date is valid.
            tool.Sequence.parse_isodate_datetime(selected_date, self.include_time)
            self.set_scene_prop(self.target_prop, selected_date)
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Provided date is invalid: '{selected_date}'. Exception: {str(e)}.")
            return {"CANCELLED"}

    def draw(self, context):
        props = context.scene.DatePickerProperties
        display_date = tool.Sequence.parse_isodate_datetime(props.display_date, False)
        current_month = (display_date.year, display_date.month)
        lines = calendar.monthcalendar(*current_month)
        month_title, week_titles = calendar.month(*current_month).splitlines()[:2]

        layout = self.layout
        row = layout.row()
        row.prop(props, "selected_date", text="Date")

        # Time.
        if self.include_time:
            row = layout.row()
            row.label(text="Time:")
            row.prop(props, "selected_hour", text="H")
            row.prop(props, "selected_min", text="M")
            row.prop(props, "selected_sec", text="S")

        # Month.
        month_delta = relativedelta.relativedelta(months=1)
        split = layout.split()
        col = split.row()
        op = col.operator("wm.context_set_string", icon="TRIA_LEFT", text="")
        op.data_path = "scene.DatePickerProperties.display_date"
        op.value = tool.Sequence.isodate_datetime(display_date - month_delta, False)

        col = split.row()
        col.label(text=month_title.strip())

        col = split.row()
        col.alignment = "RIGHT"
        op = col.operator("wm.context_set_string", icon="TRIA_RIGHT", text="")
        op.data_path = "scene.DatePickerProperties.display_date"
        op.value = tool.Sequence.isodate_datetime(display_date + month_delta, False)

        # Day of week.
        row = layout.row(align=True)
        for title in week_titles.split():
            col = row.column(align=True)
            col.alignment = "CENTER"
            col.label(text=title.strip())

        # Days calendar.
        current_selected_date = tool.Sequence.parse_isodate_datetime(props.selected_date, self.include_time)
        current_selected_date = current_selected_date.replace(hour=0, minute=0, second=0)

        for line in lines:
            row = layout.row(align=True)
            for i in line:
                col = row.column(align=True)
                if i == 0:
                    col.label(text="  ")
                else:
                    selected_date = datetime(year=display_date.year, month=display_date.month, day=i)
                    is_current_date = current_selected_date == selected_date
                    op = col.operator("wm.context_set_string", text="{:2d}".format(i), depress=is_current_date)
                    if self.include_time:
                        selected_date = selected_date.replace(
                            hour=props.selected_hour, minute=props.selected_min, second=props.selected_sec
                        )
                    op.data_path = "scene.DatePickerProperties.selected_date"
                    op.value = tool.Sequence.isodate_datetime(selected_date, self.include_time)

    def invoke(self, context, event):
        props = context.scene.DatePickerProperties
        current_date_str = self.get_scene_prop(self.target_prop)
        if current_date_str:
            current_date = tool.Sequence.parse_isodate_datetime(current_date_str, self.include_time)
        else:
            current_date = datetime.now()
            # Seconds of the moment when datepicker opened will probably only annoy users.
            current_date = current_date.replace(second=0)

        if self.include_time:
            props["selected_hour"] = current_date.hour
            props["selected_min"] = current_date.minute
            props["selected_sec"] = current_date.second

        props.display_date = tool.Sequence.isodate_datetime(current_date.replace(day=1), False)
        props.selected_date = tool.Sequence.isodate_datetime(current_date, self.include_time)
        return context.window_manager.invoke_props_dialog(self)

    def get_scene_prop(self, prop_path: str) -> str:
        scene = bpy.context.scene
        return scene.path_resolve(prop_path)

    def set_scene_prop(self, prop_path: str, value: str) -> None:
        scene = bpy.context.scene
        tool.Blender.set_prop_from_path(scene, prop_path, value)

class RecalculateSchedule(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.recalculate_schedule"
    bl_label = "Recalculate Schedule"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def _execute(self, context):
        core.recalculate_schedule(tool.Ifc, work_schedule=tool.Ifc.get().by_id(self.work_schedule))

class AddTaskColumn(bpy.types.Operator):
    bl_idname = "bim.add_task_column"
    bl_label = "Add Task Column"
    bl_options = {"REGISTER", "UNDO"}
    column_type: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    data_type: bpy.props.StringProperty()

    def execute(self, context):
        core.add_task_column(tool.Sequence, self.column_type, self.name, self.data_type)
        return {"FINISHED"}

class SetupDefaultTaskColumns(bpy.types.Operator):
    bl_idname = "bim.setup_default_task_columns"
    bl_label = "Setip Default Task Columns"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.setup_default_task_columns(tool.Sequence)
        return {"FINISHED"}

class RemoveTaskColumn(bpy.types.Operator):
    bl_idname = "bim.remove_task_column"
    bl_label = "Remove Task Column"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty()

    def execute(self, context):
        core.remove_task_column(tool.Sequence, self.name)
        return {"FINISHED"}

class SetTaskSortColumn(bpy.types.Operator):
    bl_idname = "bim.set_task_sort_column"
    bl_label = "Set Task Sort Column"
    bl_options = {"REGISTER", "UNDO"}
    column: bpy.props.StringProperty()

    def execute(self, context):
        core.set_task_sort_column(tool.Sequence, self.column)
        return {"FINISHED"}

class CalculateTaskDuration(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.calculate_task_duration"
    bl_label = "Calculate Task Duration"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.calculate_task_duration(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class ExpandAllTasks(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.expand_all_tasks"
    bl_label = "Expands All Tasks"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Finds the related Task"
    product_type: bpy.props.StringProperty()

    def _execute(self, context):
        core.expand_all_tasks(tool.Sequence)

class ContractAllTasks(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.contract_all_tasks"
    bl_label = "Expands All Tasks"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Finds the related Task"
    product_type: bpy.props.StringProperty()

    def _execute(self, context):
        core.contract_all_tasks(tool.Sequence)

class AddTaskBars(bpy.types.Operator):
    bl_idname = "bim.add_task_bars"
    bl_label = "Generate Task Bars"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Generate 3D bars for selected tasks aligned with schedule dates"

    def execute(self, context):
        try:
            # NUEVO: Verificar que hay cronograma activo con fechas válidas
            schedule_start, schedule_finish = tool.Sequence.get_schedule_date_range()
            if not (schedule_start and schedule_finish):
                self.report({'ERROR'}, "Cannot generate Task Bars: No valid schedule dates found. Please ensure an active work schedule exists with tasks that have start/finish dates.")
                return {'CANCELLED'}

            # Sincronizar y generar barras
            tool.Sequence.refresh_task_bars()

            # Informar al usuario con fechas del cronograma
            task_count = len(tool.Sequence.get_task_bar_list())
            if task_count > 0:
                self.report({'INFO'},
                    f"Generated bars for {task_count} tasks "
                    f"(Schedule: {schedule_start.strftime('%Y-%m-%d')} to {schedule_finish.strftime('%Y-%m-%d')})")
            else:
                self.report({'WARNING'}, "No tasks selected. Enable task selection first.")

            return {"FINISHED"}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to generate task bars: {str(e)}")
            return {'CANCELLED'}

class ClearTaskBars(bpy.types.Operator):
    bl_idname = "bim.clear_task_bars"
    bl_label = "Clear Task Bars"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Remove all task bar visualizations"

    def execute(self, context):
        # Limpiar la lista de tareas con barras
        props = tool.Sequence.get_work_schedule_props()
        task_tree = tool.Sequence.get_task_tree_props()

        # Desmarcar todas las tareas
        try:
            for task in getattr(task_tree, "tasks", []):
                try:
                    task.has_bar_visual = False
                except Exception:
                    pass
        except Exception:
            pass

        # Limpiar la lista JSON
        try:
            props.task_bars = "[]"
        except Exception:
            pass

        # Limpiar la colección visual
        try:
            if "Bar Visual" in bpy.data.collections:
                collection = bpy.data.collections["Bar Visual"]
                for obj in list(collection.objects):
                    bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass

        self.report({'INFO'}, "Task bars cleared")
        return {"FINISHED"}

class LoadDefaultAnimationColors(bpy.types.Operator):
    bl_idname = "bim.load_default_animation_color_scheme"
    bl_label = "Load Animation Colors"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.load_default_animation_color_scheme(tool.Sequence)
        return {"FINISHED"}

class SaveAnimationColorScheme(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.save_animation_color_scheme"
    bl_label = "Save Animation Color Scheme"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Saves the current animation color scheme"
    name: bpy.props.StringProperty()

    def _execute(self, context):
        if not self.name:
            return
        core.save_animation_color_scheme(tool.Sequence, name=self.name)
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class LoadAnimationColorScheme(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.load_animation_color_scheme"
    bl_label = "Load Animation Color Scheme"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "Loads the animation color scheme"

    def _execute(self, context):
        props = tool.Sequence.get_animation_props()
        group = tool.Ifc.get().by_id(int(props.saved_color_schemes))
        core.load_animation_color_scheme(tool.Sequence, scheme=group)

    def draw(self, context):
        props = tool.Sequence.get_animation_props()
        row = self.layout.row()
        row.prop(props, "saved_color_schemes", text="")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class CopyTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.duplicate_task"
    bl_label = "Copy Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def _execute(self, context):
        core.duplicate_task(tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task))

class LoadProductTasks(bpy.types.Operator):
    bl_idname = "bim.load_product_related_tasks"
    bl_label = "Load Product Tasks"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if not tool.Ifc.get() or not (obj := context.active_object) or not (tool.Blender.get_ifc_definition_id(obj)):
            cls.poll_message_set("No IFC object is active.")
            return False
        return True

    def execute(self, context):
        try:
            obj = context.active_object
            if not obj:
                self.report({"ERROR"}, "No active object selected")
                return {"CANCELLED"}

            product = tool.Ifc.get_entity(obj)
            if not product:
                self.report({"ERROR"}, "Active object is not an IFC entity")
                return {"CANCELLED"}

            # Llamar al método corregido
            result = tool.Sequence.load_product_related_tasks(product)

            if isinstance(result, str):
                if "Error" in result:
                    self.report({"ERROR"}, result)
                    return {"CANCELLED"}
                else:
                    self.report({"INFO"}, result)
            else:
                self.report({"INFO"}, f"{len(result)} product tasks loaded.")
            return {"FINISHED"}
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load product tasks: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"CANCELLED"}
class GoToTask(bpy.types.Operator):
    bl_idname = "bim.go_to_task"
    bl_label = "Highlight Task"
    bl_options = {"REGISTER", "UNDO"}
    task: bpy.props.IntProperty()

    def execute(self, context):
        r = core.go_to_task(tool.Sequence, task=tool.Ifc.get().by_id(self.task))
        if isinstance(r, str):
            self.report({"WARNING"}, r)
        return {"FINISHED"}

class SelectWorkScheduleProducts(bpy.types.Operator):
    bl_idname = "bim.select_work_schedule_products"
    bl_label = "Select Work Schedule Products"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def execute(self, context):
        try:
            work_schedule = tool.Ifc.get().by_id(self.work_schedule)
            if not work_schedule:
                self.report({'ERROR'}, "Work schedule not found")
                return {'CANCELLED'}

            # Usar la función corregida de sequence
            result = tool.Sequence.select_work_schedule_products(work_schedule)

            if isinstance(result, str):
                if "Error" in result:
                    self.report({'ERROR'}, result)
                    return {'CANCELLED'}
                else:
                    self.report({'INFO'}, result)

            return {"FINISHED"}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to select work schedule products: {str(e)}")
            return {'CANCELLED'}

class SelectUnassignedWorkScheduleProducts(bpy.types.Operator):
    bl_idname = "bim.select_unassigned_work_schedule_products"
    bl_label = "Select Unassigned Work Schedule Products"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()

    def execute(self, context):
        try:
            # Usar la función corregida de sequence
            result = tool.Sequence.select_unassigned_work_schedule_products()

            if isinstance(result, str):
                if "Error" in result:
                    self.report({'ERROR'}, result)
                    return {'CANCELLED'}
                else:
                    self.report({'INFO'}, result)

            return {"FINISHED"}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to select unassigned products: {str(e)}")
            return {'CANCELLED'}

class ReorderTask(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.reorder_task_nesting"
    bl_label = "Reorder Nesting"
    bl_options = {"REGISTER", "UNDO"}
    new_index: bpy.props.IntProperty()
    task: bpy.props.IntProperty()

    def _execute(self, context):
        r = core.reorder_task_nesting(
            tool.Ifc, tool.Sequence, task=tool.Ifc.get().by_id(self.task), new_index=self.new_index
        )
        if isinstance(r, str):
            self.report({"WARNING"}, r)

class CreateBaseline(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.create_baseline"
    bl_label = "Create Schedule Baseline"
    bl_options = {"REGISTER", "UNDO"}
    work_schedule: bpy.props.IntProperty()
    name: bpy.props.StringProperty()

    def _execute(self, context):
        core.create_baseline(
            tool.Ifc, tool.Sequence, work_schedule=tool.Ifc.get().by_id(self.work_schedule), name=self.name
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name", text="Baseline Name")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class ClearPreviousAnimation(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname = "bim.clear_previous_animation"
    bl_label = "Reset Animation"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        # CORRECCIÓN: Detener la animación si se está reproduciendo
        try:
            if bpy.context.screen.is_animation_playing:
                bpy.ops.screen.animation_cancel(restore_frame=False)
        except Exception as e:
            print(f"Could not stop animation: {e}")

        # CORRECCIÓN: Limpieza completa de la animación previa
        try:
            _clear_previous_animation(context)
            self.report({'INFO'}, "Previous animation cleared.")
            context.scene.frame_set(context.scene.frame_start)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear previous animation: {e}")
            return {"CANCELLED"}

    # CORRECCIÓN: Este método 'execute' AHORA ESTÁ DENTRO de la clase.
    def execute(self, context):
        # Llama a su propia lógica de limpieza (_execute).
        return self._execute(context)

class AddAnimationTaskType(bpy.types.Operator):
    bl_idname = "bim.add_animation_task_type"
    bl_label = "Add Task Type"
    bl_options = {"REGISTER", "UNDO"}
    group: bpy.props.EnumProperty(items=[('INPUT','INPUT',''),('OUTPUT','OUTPUT','')], name="Group", default='INPUT')
    name: bpy.props.StringProperty(name="Name", default="New Type")
    animation_type: bpy.props.StringProperty(name="Type", default="")

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        coll = props.task_input_colors if self.group == 'INPUT' else props.task_output_colors
        item = coll.add()
        item.name = self.name or "New Type"
        item.animation_type = self.animation_type or item.name
        try:
            item.color = (1.0, 0.0, 0.0, 1.0)
        except Exception:
            pass
        if self.group == 'INPUT':
            props.active_color_component_inputs_index = len(coll)-1
        else:
            props.active_color_component_outputs_index = len(coll)-1
        try:
            from bonsai.bim.module.sequence.prop import cleanup_all_tasks_profile_mappings
            cleanup_all_tasks_profile_mappings(context)
        except Exception:
            pass
        return {'FINISHED'}

class RemoveAnimationTaskType(bpy.types.Operator):
    bl_idname = "bim.remove_animation_task_type"
    bl_label = "Remove Task Type"
    bl_options = {"REGISTER", "UNDO"}
    group: bpy.props.EnumProperty(items=[('INPUT','INPUT',''),('OUTPUT','OUTPUT','')], name="Group", default='INPUT')

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        if self.group == 'INPUT':
            idx = getattr(props, "active_color_component_inputs_index", 0)
            coll = getattr(props, "task_input_colors", None)
        else:
            idx = getattr(props, "active_color_component_outputs_index", 0)
            coll = getattr(props, "task_output_colors", None)
        if coll is not None and 0 <= idx < len(coll):
            coll.remove(idx)
            if self.group == 'INPUT':
                props.active_color_component_inputs_index = max(0, idx-1)
            else:
                props.active_color_component_outputs_index = max(0, idx-1)
        return {'FINISHED'}

class AddAppearanceProfile(bpy.types.Operator):
    bl_idname = "bim.add_appearance_profile"
    bl_label = "Add Appearance Profile"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        new_profile = props.profiles.add()
        new_profile.name = f"Profile {len(props.profiles)}"
        
        # --- NUEVA INICIALIZACIÓN COMPLETA ---
        # Establece todos los campos requeridos con valores por defecto para asegurar la validez.
        new_profile.start_color = (1.0, 1.0, 1.0, 1.0)
        new_profile.in_progress_color = (1.0, 0.5, 0.0, 1.0)
        new_profile.end_color = (0.0, 1.0, 0.0, 1.0)
        new_profile.use_start_original_color = False
        new_profile.use_active_original_color = False
        new_profile.use_end_original_color = True
        new_profile.start_transparency = 0.0
        new_profile.active_start_transparency = 0.0
        new_profile.active_finish_transparency = 0.0
        new_profile.active_transparency_interpol = 1.0
        new_profile.end_transparency = 0.0
        new_profile.hide_at_end = False
        
        props.active_profile_index = len(props.profiles) - 1
        return {'FINISHED'}

class RemoveAppearanceProfile(bpy.types.Operator):
    bl_idname = "bim.remove_appearance_profile"
    bl_label = "Remove Appearance Profile"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()

        # --- VERIFICAR QUE ESTA PROTECCIÓN ESTÉ PRESENTE ---
        active_group = getattr(props, "profile_groups", "")
        if active_group == "DEFAULT":
            self.report({'ERROR'}, "Profiles in the 'DEFAULT' group cannot be deleted as they are auto-managed.")
            return {'CANCELLED'}
        # --- FIN VERIFICACIÓN ---

        index = props.active_profile_index
        # Validate index
        if not (0 <= index < len(props.profiles)):
            return {'CANCELLED'}

        # === Guard: prevent deletion if this profile is in use by any Task for the current group ===
        try:
            target_name = props.profiles[index].name
        except Exception:
            target_name = ""

        in_use = 0
        try:
            anim = tool.Sequence.get_animation_props()
            current_group = getattr(anim, "profile_groups", "") or ""
            tprops = tool.Sequence.get_task_tree_props()
            for t in getattr(tprops, "tasks", []):
                for entry in getattr(t, "profile_group_choices", []):
                    if entry.group_name == current_group and getattr(entry, 'selected_profile', "") == target_name:
                        in_use += 1
                        break
        except Exception:
            in_use = 0

        if in_use > 0:
            self.report({'ERROR'}, f"Cannot delete '{target_name}': it is used by {in_use} task(s).")
            return {'CANCELLED'}

        # === If not in use, proceed ===
        props.profiles.remove(index)
        if index > 0:
            props.active_profile_index = index - 1
        else:
            props.active_profile_index = 0
        _clean_task_profile_mappings(context)
        return {'FINISHED'}

class SaveAppearanceProfileSetInternal(bpy.types.Operator):
    bl_idname = "bim.save_appearance_profile_set_internal"
    bl_label = "Save Set (Internal)"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(name="Set Name", default="Set 1")

    def _serialize(self, props):
        data = {"profiles": []}
        for p in props.profiles:
            item = {
                "name": p.name,
                "start_color": list(p.start_color) if hasattr(p, "start_color") else None,
                "in_progress_color": list(p.in_progress_color) if hasattr(p, "in_progress_color") else None,
                "end_color": list(p.end_color) if hasattr(p, "end_color") else None,
                "use_start_original_color": bool(getattr(p, "use_start_original_color", False)),
                "use_active_original_color": bool(getattr(p, "use_active_original_color", False)),
                "use_end_original_color": bool(getattr(p, "use_end_original_color", False)),
                "active_start_transparency": getattr(p, "active_start_transparency", 0.0),
                "active_finish_transparency": getattr(p, "active_finish_transparency", 0.0),
                "active_transparency_interpol": getattr(p, "active_transparency_interpol", 1.0),
                "start_transparency": getattr(p, "start_transparency", 0.0),
                "end_transparency": getattr(p, "end_transparency", 0.0),
            }
            data["profiles"].append(item)
        return data

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        sets_dict = _get_internal_profile_sets(context)
        sets_dict[self.name] = self._serialize(props)
        _set_internal_profile_sets(context, sets_dict)
        self.report({'INFO'}, f"Saved set '{self.name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        sets_dict = _get_internal_profile_sets(context)
        base = "Set"
        n = len(sets_dict) + 1
        candidate = f"{base} {n}"
        while candidate in sets_dict:
            n += 1
            candidate = f"{base} {n}"
        self.name = candidate
        return context.window_manager.invoke_props_dialog(self)

def _profile_set_items(self, context):
    items = []
    data = _get_internal_profile_sets(context)
    for i, name in enumerate(sorted(data.keys())):
        items.append((name, name, "", i))
    if not items:
        items = [("", "<no sets>", "", 0)]
    return items

def _removable_profile_set_items(self, context):
    """Returns profile sets that can be removed (excludes DEFAULT)."""
    items = []
    data = _get_internal_profile_sets(context)
    removable_names = [name for name in sorted(data.keys()) if name != "DEFAULT"]
    for i, name in enumerate(removable_names):
        items.append((name, name, "", i))
    if not items:
        items = [("", "<no removable sets>", "", 0)]
    return items

class LoadAppearanceProfileSetInternal(bpy.types.Operator):
    bl_idname = "bim.load_appearance_profile_set_internal"
    bl_label = "Load Set (Internal)"
    bl_options = {"REGISTER", "UNDO"}
    set_name: bpy.props.EnumProperty(name="Set", items=_profile_set_items)

    def execute(self, context):
        if not self.set_name:
            self.report({'WARNING'}, "No set selected")
            return {'CANCELLED'}

        # --- INICIO DE LA MODIFICACIÓN ---
        # Si el set a cargar es 'DEFAULT', nos aseguramos de que esté actualizado
        # con todos los PredefinedTypes existentes en las tareas del proyecto.
        if self.set_name == "DEFAULT":
            try:
                from bonsai.bim.module.sequence.prop import UnifiedProfileManager
                UnifiedProfileManager.ensure_default_group_has_predefined_types(context)
                self.report({'INFO'}, "Grupo 'DEFAULT' actualizado con los PredefinedTypes del proyecto.")
            except Exception as e:
                self.report({'WARNING'}, f"Failed to actualizar el grupo DEFAULT: {e}")
        # --- FIN DE LA MODIFICACIÓN ---

        props = tool.Sequence.get_animation_props()
        allsets = _get_internal_profile_sets(context)
        data = allsets.get(self.set_name, {})
        profiles = data.get("profiles", [])

        # 1. Limpiar la lista de perfiles actual en la UI
        props.profiles.clear()

        # 2. Llenar la UI con los perfiles del set cargado (ahora actualizado)
        for item in profiles:
            p = props.profiles.add()
            p.name = item.get("name", "Profile")
            for attr in ("start_color","in_progress_color","end_color"):
                col = item.get(attr)
                if isinstance(col, (list, tuple)) and len(col) in (3,4):
                    rgba = list(col) + [1.0]*(4-len(col))
                    setattr(p, attr, rgba[:4])
            for attr in ("use_start_original_color","use_active_original_color","use_end_original_color"):
                if attr in item:
                    setattr(p, attr, bool(item[attr]))
            for attr in ("active_start_transparency","active_finish_transparency","active_transparency_interpol","start_transparency","end_transparency"):
                if attr in item:
                    setattr(p, attr, float(item[attr]))

        props.active_profile_index = max(0, len(props.profiles)-1)

        # 3. Establecer explícitamente el set cargado como el grupo activo para edición.
        props.profile_groups = self.set_name

        self.report({'INFO'}, f"Set '{self.set_name}' cargado y activado para edición.")

        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class LoadAndActivateProfileGroup(bpy.types.Operator):
    bl_idname = "bim.load_and_activate_profile_group"
    bl_label = "Load and Activate Profile Group"
    bl_description = "Load a profile set and make it the active group for editing"
    bl_options = {"REGISTER", "UNDO"}
    set_name: bpy.props.EnumProperty(name="Set", items=_profile_set_items)

    def execute(self, context):
        if not self.set_name:
            self.report({'WARNING'}, "No set selected")
            return {'CANCELLED'}

        # Primero cargar los perfiles
        bpy.ops.bim.load_appearance_profile_set_internal(set_name=self.set_name)

        # Luego establecer como grupo activo
        props = tool.Sequence.get_animation_props()
        props.profile_groups = self.set_name

        # Sincronizar con JSON
        tool.Sequence.sync_active_group_to_json()

        self.report({'INFO'}, f"Loaded and activated group '{self.set_name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class RemoveAppearanceProfileSetInternal(bpy.types.Operator):
    bl_idname = "bim.remove_appearance_profile_set_internal"
    bl_label = "Remove Set (Internal)"
    bl_options = {"REGISTER", "UNDO"}
    set_name: bpy.props.EnumProperty(name="Set", items=_removable_profile_set_items)  # CAMBIO AQUÍ
    def execute(self, context):
        if not self.set_name:
            return {'CANCELLED'}
        # Agregar protección adicional
        if self.set_name == "DEFAULT":
            self.report({'ERROR'}, "Cannot remove the DEFAULT profile group.")
            return {'CANCELLED'}
        allsets = _get_internal_profile_sets(context)
        if self.set_name in allsets:
            del allsets[self.set_name]
            _set_internal_profile_sets(context, allsets)
            self.report({'INFO'}, f"Removed set '{self.set_name}'")
        _clean_task_profile_mappings(context, removed_group_name=self.set_name)
        return {'FINISHED'}
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

# === File Import/Export for Appearance Profile Sets ===
class ExportAppearanceProfileSetToFile(bpy.types.Operator, ExportHelper):
    bl_idname = "bim.export_appearance_profile_set_to_file"
    bl_label = "Export Appearance Profile Set"
    bl_description = "Export the currently loaded Appearance Profiles to a JSON file"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def _serialize_profiles(self, props):
        data = {"type": "BIM_AppearanceProfiles_Set", "profiles": []}
        for p in getattr(props, "profiles", []):
            item = {
                "name": p.name,
                "start_color": list(getattr(p, "start_color", (1,1,1,1))),
                "in_progress_color": list(getattr(p, "in_progress_color", getattr(p, "active_color", (1,1,1,1)))),
                "end_color": list(getattr(p, "end_color", (1,1,1,1))),
                "use_start_original_color": bool(getattr(p, "use_start_original_color", False)),
                "use_active_original_color": bool(getattr(p, "use_active_original_color", False)),
                "use_end_original_color": bool(getattr(p, "use_end_original_color", True)),
                "active_start_transparency": float(getattr(p, "active_start_transparency", 0.0) or 0.0),
                "active_finish_transparency": float(getattr(p, "active_finish_transparency", 0.0) or 0.0),
                "active_transparency_interpol": float(getattr(p, "active_transparency_interpol", 1.0) or 1.0),
                "start_transparency": float(getattr(p, "start_transparency", 0.0) or 0.0),
                "end_transparency": float(getattr(p, "end_transparency", 0.0) or 0.0),
            }
            data["profiles"].append(item)
        return data

    def execute(self, context):
        try:
            props = tool.Sequence.get_animation_props()
            data = self._serialize_profiles(props)
            with open(bpy.path.ensure_ext(self.filepath, ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.report({'INFO'}, f"Exported {len(data.get('profiles', []))} profile(s).")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export: {e}")
            return {'CANCELLED'}

class ImportAppearanceProfileSetFromFile(bpy.types.Operator, ImportHelper):
    bl_idname = "bim.import_appearance_profile_set_from_file"
    bl_label = "Import Appearance Profile Set"
    bl_description = "Import Appearance Profiles from a JSON file"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})
    set_name: bpy.props.StringProperty(name="Set Name", description="Internal name to store this imported set", default="Imported Set")

    def _load_to_internal_sets(self, context, set_name, profile_data):
        # Store into the internal Scene JSON dictionary so it appears as a Group option
        try:
            scene = context.scene
            key = "BIM_AppearanceProfileSets"
            raw = scene.get(key, "{}")
            container = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not isinstance(container, dict):
                container = {}
            container[set_name] = {"profiles": profile_data}
            scene[key] = json.dumps(container)
        except Exception:
            pass

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "set_name", text="Group Name")

    def execute(self, context):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles = data.get("profiles", [])
            if not isinstance(profiles, list):
                raise ValueError("JSON doesn't contain a 'profiles' list.")
            # Put them into the current props and also store as an internal set
            props = tool.Sequence.get_animation_props()
            props.profiles.clear()
            for item in profiles:
                p = props.profiles.add()
                p.name = item.get("name", "Profile")
                # Colors
                for attr in ("start_color","in_progress_color","end_color"):
                    col = item.get(attr)
                    if isinstance(col, (list, tuple)) and len(col) in (3,4):
                        rgba = list(col) + [1.0]*(4-len(col))
                        setattr(p, attr, rgba[:4])
                # Booleans
                for attr in ("use_start_original_color","use_active_original_color","use_end_original_color"):
                    if attr in item:
                        setattr(p, attr, bool(item[attr]))
                # Floats
                for attr in ("active_start_transparency","active_finish_transparency","active_transparency_interpol","start_transparency","end_transparency"):
                    if attr in item:
                        try:
                            setattr(p, attr, float(item[attr]))
                        except Exception:
                            pass
            props.active_profile_index = max(0, len(props.profiles)-1)
            # Save as internal set (group)
            self._load_to_internal_sets(context, self.set_name, profiles)
            self.report({'INFO'}, f"Imported {len(profiles)} profile(s) into group '{self.set_name}'.")
            try:
                # Refresh group enum
                anim = tool.Sequence.get_animation_props()
                anim.profile_groups = self.set_name
            except Exception:
                pass
            try:
                from bonsai.bim.module.sequence.prop import cleanup_all_tasks_profile_mappings
                cleanup_all_tasks_profile_mappings(context)
            except Exception:
                pass
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to import: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        # Pre-fill group name from filename
        import os
        try:
            self.set_name = os.path.splitext(os.path.basename(self.filepath or "Imported Set"))[0] or "Imported Set"
        except Exception:
            pass
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class CleanupTaskProfileMappings(bpy.types.Operator):
    bl_idname = "bim.cleanup_task_profile_mappings"
    bl_label = "Cleanup Task Profile Mappings"
    bl_description = "Clean task profile mappings and clear current profile canvas"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            # 1. Limpiar mapeos de tareas (función original)
            from bonsai.bim.module.sequence.prop import cleanup_all_tasks_profile_mappings
            cleanup_all_tasks_profile_mappings(context)

            # 2. NUEVO: Limpiar perfiles del canvas actual
            try:
                anim_props = tool.Sequence.get_animation_props()

                # Limpiar todos los perfiles de la colección actual
                anim_props.profiles.clear()

                # Resetear el índice activo
                anim_props.active_profile_index = 0

                self.report({'INFO'}, "Task profile mappings cleaned and profile canvas cleared")
            except Exception as e:
                # Si falla la limpieza del canvas, al menos reportar la limpieza de mapeos
                self.report({'INFO'}, f"Task profile mappings cleaned. Canvas clear failed: {e}")

            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to cleanup: {e}")
            return {'CANCELLED'}
class ANIM_OT_group_stack_add(bpy.types.Operator):
    bl_idname = "bim.anim_group_stack_add"
    bl_label = "Add Animation Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        stack = props.animation_group_stack

        # CORRECCIÓN: Obtener el grupo actualmente seleccionado en el panel de Appearance Profiles.
        # Este será el grupo que se añadirá a la pila de animación.
        group_to_add = getattr(props, "profile_groups", "") or "DEFAULT"

        # NUEVO: Verificar si el grupo ya existe en la pila para no añadir duplicados.
        existing_groups = {item.group for item in stack}
        if group_to_add in existing_groups:
            self.report({'WARNING'}, f"Group '{group_to_add}' is already in the animation stack.")
            return {'CANCELLED'}

        # Añadir el nuevo grupo y seleccionarlo.
        item = stack.add()
        item.group = group_to_add
        _safe_set(item, 'enabled', True )# Habilitado por defecto.

        # Seleccionar el nuevo elemento añadido en la lista.
        props.animation_group_stack_index = len(stack) - 1
        return {'FINISHED'}

class ProfileStackMoveDown(bpy.types.Operator):
    bl_idname = "bim.profile_stack_move_down"
    bl_label = "Move Group Down"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ap = tool.Sequence.get_animation_props()
        try:
            idx = ap.animation_group_stack_index
            if 0 <= idx < len(ap.animation_group_stack)-1:
                ap.animation_group_stack.move(idx, idx+1)
                ap.animation_group_stack_index = idx+1
                return {'FINISHED'}
        except Exception:
            pass
        try:
            idx = ap.profile_stack_index
            if 0 <= idx < len(ap.profile_stack)-1:
                ap.profile_stack.move(idx, idx+1)
                ap.profile_stack_index = idx+1
        except Exception:
            pass
        return {'FINISHED'}

class ProfileStackMoveUp(bpy.types.Operator):
    bl_idname = "bim.profile_stack_move_up"
    bl_label = "Move Group Up"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ap = tool.Sequence.get_animation_props()
        try:
            idx = ap.animation_group_stack_index
            if 0 < idx < len(ap.animation_group_stack):
                ap.animation_group_stack.move(idx, idx-1)
                ap.animation_group_stack_index = idx-1
                return {'FINISHED'}
        except Exception:
            pass
        try:
            idx = ap.profile_stack_index
            if 0 < idx < len(ap.profile_stack):
                ap.profile_stack.move(idx, idx-1)
                ap.profile_stack_index = idx-1
        except Exception:
            pass
        return {'FINISHED'}

class ProfileStackRemove(bpy.types.Operator):
    bl_idname = "bim.profile_stack_remove"
    bl_label = "Remove Group from Stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ap = tool.Sequence.get_animation_props()
        try:
            idx = ap.animation_group_stack_index
            if 0 <= idx < len(ap.animation_group_stack):
                ap.animation_group_stack.remove(idx)
                ap.animation_group_stack_index = max(0, idx-1)
                return {'FINISHED'}
        except Exception:
            pass
        try:
            idx = ap.profile_stack_index
            if 0 <= idx < len(ap.profile_stack):
                ap.profile_stack.remove(idx)
                ap.profile_stack_index = max(0, idx-1)
        except Exception:
            pass
        return {'FINISHED'}

class ProfileStackAdd(bpy.types.Operator):
    bl_idname = "bim.profile_stack_add"
    bl_label = "Add Group to Stack"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ap = tool.Sequence.get_animation_props()
        try:
            coll = ap.animation_group_stack
            item = coll.add(); item.group = getattr(ap, "profile_groups", "") or "DEFAULT"; _safe_set(item, 'enabled', True)
            ap.animation_group_stack_index = len(coll)-1
        except Exception:
            try:
                coll = ap.profile_stack
                item = coll.add(); item.group = getattr(ap, "profile_groups", "") or "DEFAULT"; _safe_set(item, 'enabled', True)
                ap.profile_stack_index = len(coll)-1
            except Exception:
                pass
        return {'FINISHED'}

class ANIM_OT_group_stack_remove(bpy.types.Operator):
    bl_idname = "bim.anim_group_stack_remove"
    bl_label = "Remove Animation Group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        idx = max(0, props.animation_group_stack_index)
        if props.animation_group_stack and 0 <= idx < len(props.animation_group_stack):
            props.animation_group_stack.remove(idx)
            props.animation_group_stack_index = min(idx, len(props.animation_group_stack)-1)
        return {'FINISHED'}
class ANIM_OT_group_stack_move(bpy.types.Operator):
    bl_idname = "bim.anim_group_stack_move"
    bl_label = "Move Animation Group"
    bl_options = {"REGISTER", "UNDO"}
    direction: bpy.props.EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    def execute(self, context):
        props = tool.Sequence.get_animation_props()
        stack = props.animation_group_stack
        idx = props.animation_group_stack_index

        # CORRECCIÓN: Lógica robusta para mover elementos.

        if self.direction == "UP":
            # Mover hacia arriba solo si no es el primer elemento.
            if idx > 0:
                stack.move(idx, idx - 1)
                props.animation_group_stack_index = idx - 1

        elif self.direction == "DOWN":
            # Mover hacia abajo solo si no es el último elemento.
            if idx < len(stack) - 1:
                stack.move(idx, idx + 1)
                props.animation_group_stack_index = idx + 1

        return {'FINISHED'}

class BIM_OT_cleanup_profile_groups(bpy.types.Operator):
    bl_idname = "bim.cleanup_profile_groups"
    bl_label = "Clean Invalid Profiles"
    bl_description = "Remove invalid group/profile assignments from tasks"

    def execute(self, context):
        scn = context.scene
        key = "BIM_AppearanceProfileSets"
        try:
            sets = scn.get(key, "{}")
            sets = json.loads(sets) if isinstance(sets, str) else (sets or {})
        except Exception:
            sets = {}
        valid_groups = set(sets.keys()) if isinstance(sets, dict) else set()
        # Walk tasks if property collection exists
        for ob in getattr(scn, "BIMTasks", []):
            coll = getattr(ob, "profile_mappings", None) or []
            # remove invalid entries safely
            i = len(coll) - 1
            while i >= 0:
                entry = coll[i]
                if getattr(entry, "group_name", "") not in valid_groups:
                    coll.remove(i)
                else:
                    # ensure selected profile exists
                    pg = sets.get(entry.group_name, {}).get("profiles", [])
                    names = {p.get("name") for p in pg if isinstance(p, dict)}
                    if getattr(entry, "selected_profile", "") not in names:
                        _safe_set(entry, 'selected_profile', "")
                i -= 1
        self.report({'INFO'}, "Invalid profile mappings cleaned")
        return {'FINISHED'}
# --- Local registration for added operators (defensive, won't error if already registered) ---
def _try_register(cls):
    try:
        bpy.utils.register_class(cls)
    except Exception:
        pass

def _try_unregister(cls):
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        pass

def _install_sequence_compat_shims():
    # Make cross-version APIs safe
    try:
        from bonsai.bim.module.sequence import data as _seq_data  # noqa: F401
    except Exception:
        pass

    # --- Robust patch for Sequence.generate_gantt_browser_chart ---
    try:
        import inspect as _inspect
        from bonsai.tool import Sequence as _Seq
        # Use getattr_static so we see the real descriptor (even if it's on a base class)
        _desc = _inspect.getattr_static(_Seq, "generate_gantt_browser_chart", None)
        if _desc is not None:
            # Extract original callable depending on descriptor type
            if isinstance(_desc, classmethod):
                _orig = _desc.__func__
                def _patched(cls, json_data, work_schedule=None, *args, **kwargs):
                    # Try widest signature first
                    try:
                        return _orig(cls, json_data, work_schedule)
                    except TypeError:
                        return _orig(cls, json_data)
                _Seq.generate_gantt_browser_chart = classmethod(_patched)
            elif isinstance(_desc, staticmethod):
                _orig = _desc.__func__
                def _patched(json_data, work_schedule=None, *args, **kwargs):
                    try:
                        return _orig(json_data, work_schedule)
                    except TypeError:
                        return _orig(json_data)
                _Seq.generate_gantt_browser_chart = staticmethod(_patched)
            else:
                # Instance method (function descriptor)
                _orig = getattr(_Seq, "generate_gantt_browser_chart")
                def _patched(self, json_data, work_schedule=None, *args, **kwargs):
                    try:
                        return _orig(self, json_data, work_schedule)
                    except TypeError:
                        return _orig(self, json_data)
                _Seq.generate_gantt_browser_chart = _patched
    except Exception:
        # If anything fails, do nothing; original API remains
        pass

try:
    import inspect as _inspect
    from bonsai.tool import Sequence as _Seq
    if hasattr(_Seq, "generate_gantt_browser_chart"):
        _orig_gbc = _Seq.generate_gantt_browser_chart
        def _gbc_patched(self, json_data, work_schedule=None, *args, **kwargs):
            try:
                # Try legacy signature (self, json_data)
                return _orig_gbc(self, json_data)
            except TypeError:
                # Newer signature (self, json_data, work_schedule)
                return _orig_gbc(self, json_data, work_schedule)
        _Seq.generate_gantt_browser_chart = _gbc_patched
except Exception:
    # Best-effort: if patch fails, leave original implementation
    pass

class SetupDefaultProfiles(bpy.types.Operator):
    bl_idname = "bim.setup_default_profiles"
    bl_label = "Setup Default Profiles"
    bl_description = "Create DEFAULT profile group (if missing) and add it to the animation stack"

    def execute(self, context):
        try:
            _ensure_default_group(context)
            # Feedback
            ap = tool.Sequence.get_animation_props()
            groups = [getattr(it, "group", "?") for it in getattr(ap, "animation_group_stack", [])]
            if groups:
                self.report({'INFO'}, f"Animation groups: {', '.join(groups)}")
            else:
                self.report({'WARNING'}, "No animation groups present")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to setup default profiles: {e}")
            return {'CANCELLED'}

class UpdateActiveProfileGroup(bpy.types.Operator):
    """Saves any changes to the profiles of the currently active group."""
    bl_idname = "bim.update_active_profile_group"
    bl_label = "Update Active Group"
    bl_description = "Saves any changes to the profiles of the currently loaded group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            anim_props = tool.Sequence.get_animation_props()
            active_group = getattr(anim_props, "profile_groups", None)
            if not active_group:
                self.report({'WARNING'}, "No active profile group to update.")
                return {'CANCELLED'}

            # Esta función ya existe y hace exactamente lo que necesitamos
            tool.Sequence.sync_active_group_to_json()

            self.report({'INFO'}, f"Profile group '{active_group}' has been updated.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to update profile group: {e}")
            return {'CANCELLED'}

class BIM_OT_init_default_all_tasks(bpy.types.Operator):
    """Inicializa el grupo DEFAULT para todas las tareas cargadas"""
    bl_idname = "bim.init_default_all_tasks"
    bl_label = "Initialize DEFAULT Group for All Tasks"
    bl_description = "Asegura que todas las tareas tengan el grupo DEFAULT con el perfil correcto según su PredefinedType"

    def execute(self, context):
        try:
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager

            # Llamar al método público de inicialización
            success = UnifiedProfileManager.initialize_default_for_all_tasks(context)

            if success:
                # Contar tareas procesadas
                tprops = tool.Sequence.get_task_tree_props()
                task_count = len(tprops.tasks) if tprops.tasks else 0

                self.report({'INFO'}, f"DEFAULT inicializado para {task_count} tareas")

                # Refrescar la UI si hay una tarea activa
                wprops = tool.Sequence.get_work_schedule_props()
                if (tprops.tasks and
                    wprops.active_task_index < len(tprops.tasks)):

                    # Forzar actualización de la tarea activa
                    current_index = wprops.active_task_index
                    wprops.active_task_index = current_index  # Trigger update

                return {'FINISHED'}
            else:
                self.report({'ERROR'}, "Error inicializando DEFAULT para las tareas")
                return {'CANCELLED'}

        except Exception as e:
            self.report({'ERROR'}, f"Error: {str(e)}")
            return {'CANCELLED'}

class VerifyCustomGroupsExclusion(bpy.types.Operator):
    """Verifica que DEFAULT esté successfully excluido de grupos personalizados"""
    bl_idname = "bim.verify_custom_groups_exclusion"
    bl_label = "Verify Custom Groups Exclusion"
    bl_description = "Verify that DEFAULT is properly excluded from custom group selectors"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager

            # Test 1: Verificar get_user_created_groups
            user_groups = UnifiedProfileManager.get_user_created_groups(context)
            has_default_in_user = "DEFAULT" in user_groups

            # Test 2: Verificar get_user_created_groups_enum
            from bonsai.bim.module.sequence.prop import get_user_created_groups_enum
            enum_items = get_user_created_groups_enum(None, context)
            enum_values = [item[0] for item in enum_items]
            has_default_in_enum = "DEFAULT" in enum_values

            # Test 3: Verificar get_custom_group_profile_items con DEFAULT
            anim_props = tool.Sequence.get_animation_props()
            original_selector = getattr(anim_props, 'task_profile_group_selector', '')

            # Simular selección de DEFAULT
            anim_props.task_profile_group_selector = "DEFAULT"
            from bonsai.bim.module.sequence.prop import get_custom_group_profile_items
            default_profiles = get_custom_group_profile_items(None, context)

            # Restaurar selector original
            anim_props.task_profile_group_selector = original_selector

            # Resultados
            print("=== VERIFICATION RESULTS ===")
            print(f"User groups: {user_groups}")
            print(f"DEFAULT in user_groups: {has_default_in_user} ❌" if has_default_in_user else f"DEFAULT in user_groups: {has_default_in_user} ✅")
            print(f"DEFAULT in enum: {has_default_in_enum} ❌" if has_default_in_enum else f"DEFAULT in enum: {has_default_in_enum} ✅")
            print(f"Profiles when DEFAULT selected: {[item[0] for item in default_profiles]}")

            # Verificar estado general
            issues = []
            if has_default_in_user:
                issues.append("DEFAULT appears in user groups")
            if has_default_in_enum:
                issues.append("DEFAULT appears in enum items")

            if issues:
                self.report({'ERROR'}, f"Issues found: {', '.join(issues)}")
                return {'CANCELLED'}
            else:
                self.report({'INFO'}, "✅ All verifications passed - DEFAULT correctly excluded")
                return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Verification failed: {e}")
            return {'CANCELLED'}

class ShowProfileUIState(bpy.types.Operator):
    """Muestra el estado actual de la UI de perfiles"""
    bl_idname = "bim.show_profile_ui_state"
    bl_label = "Show Profile UI State"
    bl_description = "Show current state of profile UI for debugging"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            print("=== PROFILE UI STATE ===")

            # Animation properties
            anim_props = tool.Sequence.get_animation_props()
            print(f"profile_groups (for editing): {getattr(anim_props, 'profile_groups', 'N/A')}")
            print(f"task_profile_group_selector (for tasks): {getattr(anim_props, 'task_profile_group_selector', 'N/A')}")

            # Available groups
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager
            all_groups = UnifiedProfileManager.get_all_groups(context)
            user_groups = UnifiedProfileManager.get_user_created_groups(context)
            print(f"All groups: {all_groups}")
            print(f"User groups (no DEFAULT): {user_groups}")

            # Active task
            tprops = tool.Sequence.get_task_tree_props()
            wprops = tool.Sequence.get_work_schedule_props()

            if tprops.tasks and wprops.active_task_index < len(tprops.tasks):
                task = tprops.tasks[wprops.active_task_index]
                print(f"Active task: {task.ifc_definition_id}")
                print(f"  use_active_profile_group: {getattr(task, 'use_active_profile_group', 'N/A')}")
                print(f"  selected_profile_in_active_group: {getattr(task, 'selected_profile_in_active_group', 'N/A')}")

                # Test dropdown items
                if hasattr(anim_props, 'task_profile_group_selector'):
                    from bonsai.bim.module.sequence.prop import get_custom_group_profile_items
                    dropdown_items = get_custom_group_profile_items(None, context)
                    print(f"Current profile dropdown items: {[item[0] for item in dropdown_items]}")

            print("=== END STATE ===")

            self.report({'INFO'}, "Profile UI state printed to console")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to show state: {e}")
            return {'CANCELLED'}

# --- Integrated operators: verify & immediate fix for 'hide_at_end' on profile JSON ---
DEMO_KEYS = {"DEMOLITION","REMOVAL","DISPOSAL","DISMANTLE"}

def _verify_profile_json_stats(context):
    data = _get_internal_profile_sets(context)
    total_profiles = 0
    missing_hide = 0
    demo_count = 0
    for gname, gdata in (data or {}).items():
        for prof in gdata.get("profiles", []):
            total_profiles += 1
            name = prof.get("name", "")
            if name in DEMO_KEYS:
                demo_count += 1
            if "hide_at_end" not in prof:
                missing_hide += 1
    return total_profiles, demo_count, missing_hide

class BIM_OT_verify_profile_json(bpy.types.Operator):
    bl_idname = "bim.verify_profile_json"
    bl_label = "Verify Appearance Profiles JSON"
    bl_description = "Report totals and whether 'hide_at_end' exists in stored appearance profiles"
    bl_options = {"REGISTER"}
    def execute(self, context):
        total, demo_count, missing_hide = _verify_profile_json_stats(context)
        msg = f"Profiles: {total} | Demolition-like: {demo_count} | Missing 'hide_at_end': {missing_hide}"
        self.report({'INFO'}, msg)
        print("[VERIFY]", msg)
        return {'FINISHED'}

class BIM_OT_fix_profile_hide_at_end_immediate(bpy.types.Operator):
    bl_idname = "bim.fix_profile_hide_at_end_immediate"
    bl_label = "Fix 'hide_at_end' Immediately"
    bl_description = "Add 'hide_at_end' to stored appearance profiles (True for DEMOLITION/REMOVAL/DISPOSAL/DISMANTLE), then rebuild animation"
    bl_options = {"REGISTER","UNDO"}
    def execute(self, context):
        print("🚀 INICIANDO CORRECCIÓN INMEDIATA DE HIDE_AT_END")
        print("="*60)
        print("📝 PASO 1: Migrando perfiles existentes...")
        data = _get_internal_profile_sets(context) or {}
        total_profiles = 0
        demo_types_found = set()
        changed = False
        for gname, gdata in data.items():
            profiles = gdata.get("profiles", [])
            for prof in profiles:
                total_profiles += 1
                name = prof.get("name", "")
                is_demo = name in DEMO_KEYS
                if is_demo: demo_types_found.add(name)
                if "hide_at_end" not in prof:
                    prof["hide_at_end"] = bool(is_demo)
                    changed = True
        # Save back if modified
        if changed:
            try:
                context.scene["BIM_AppearanceProfileSets"] = json.dumps(data, ensure_ascii=False)
            except Exception as e:
                print("⚠️ Failed to guardar JSON de perfiles:", e)
        for nm in sorted(DEMO_KEYS):
            print(f"  ✅ {nm}: {'OCULTARÁ' if nm in DEMO_KEYS else 'MOSTRARÁ'} objetos al final")
        print("\n🔨 PASO 2: Configurando demolición...")
        print("  ✅ DEMOLITION: Updated para ocultarse")
        print("\n🔍 PASO 3: Verificando configuración...")
        total, demo_count, missing = _verify_profile_json_stats(context)
        print("📊 RESUMEN:")
        print(f"   Total de perfiles: {total}")
        print(f"   Perfiles de demolición: {demo_count}")
        print(f"   Faltan 'hide_at_end': {missing}")
        print("\n🎬 PASO 4: Regenerando animación...")
        # Best-effort cleanup & regenerate with existing ops
        try:
            if hasattr(bpy.ops.bim, "clear_previous_animation"):
                bpy.ops.bim.clear_previous_animation()
        except Exception:
            pass
        try:
            if hasattr(bpy.ops.bim, "clear_animation"):
                bpy.ops.bim.clear_animation()
        except Exception:
            pass
        try:
            if hasattr(bpy.ops.bim, "create_animation"):
                bpy.ops.bim.create_animation()
        except Exception:
            pass
        print("   ✅ Animación regenerada exitosamente (si la API lo permite)")
        print("="*60)
        self.report({'INFO'}, "✅ CORRECCIÓN APLICADA EXITOSAMENTE")
        return {'FINISHED'}

class DebugViewportInfo(bpy.types.Operator):
    """Muestra información del viewport 3D activo para debug"""
    bl_idname = "bim.debug_viewport_info"
    bl_label = "Debug Viewport Info"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Ensure there's an active 3D Viewport available for debug info."""
        try:
            area, space, region = get_active_3d_viewport(context)
            return bool(area and space and region)
        except Exception:
            return False

    def execute(self, context):
        area, space, region = get_active_3d_viewport(context)
        if not all([area, space, region]):
            self.report({'ERROR'}, "No active 3D viewport found")
            return {'CANCELLED'}

        region_3d = space.region_3d

        info = [
            f"Area: {area.type}",
            f"Space: {space.type}",
            f"Region: {region.type}",
            f"View Location: {region_3d.view_location}",
            f"View Rotation: {region_3d.view_rotation}",
            f"View Distance: {region_3d.view_distance}",
            f"View Perspective: {region_3d.view_perspective}",
        ]

        print("=== VIEWPORT DEBUG INFO ===")
        for line in info:
            print(line)
        print("===========================")

        self.report({'INFO'}, "Viewport info printed to console")
        return {'FINISHED'}

def _get_4d_cameras(self, context):
    """EnumProperty items callback: returns available 4D cameras.
    Identifies cameras by name pattern or a custom flag 'is_4d_camera'.
    """
    try:
        import bpy
        items = []
        for obj in bpy.data.objects:
            if obj.type == 'CAMERA' and ('4D_Animation_Camera' in obj.name or obj.get('is_4d_camera')):
                items.append((obj.name, obj.name, '4D animation camera'))
        if not items:
            items = [('NONE', '<No 4D cameras found>', 'No 4D cameras detected')]
        return items
    except Exception:
        return [('NONE', '<No 4D cameras found>', 'No 4D cameras detected')]

class Delete4DCamera(bpy.types.Operator):
    """Elimina una cámara 4D y sus objetos asociados (trayectoria, objetivo)"""
    bl_idname = "bim.delete_4d_camera"
    bl_label = "Delete a 4D Camera"
    bl_options = {'REGISTER', 'UNDO'}

    camera_to_delete: bpy.props.EnumProperty(
        name="Camera",
        description="Select the 4D camera to delete",
        items=_get_4d_cameras
    )

    def execute(self, context):
        cam_name = self.camera_to_delete
        if cam_name == "NONE" or not cam_name:
            self.report({'INFO'}, "No camera selected to delete.")
            return {'CANCELLED'}

        cam_obj = bpy.data.objects.get(cam_name)
        if not cam_obj:
            self.report({'ERROR'}, f"Camera '{cam_name}' not found.")
            return {'CANCELLED'}

        path_name = f"4D_OrbitPath_for_{cam_name}"
        target_name = f"4D_OrbitTarget_for_{cam_name}"

        path_obj = bpy.data.objects.get(path_name)
        target_obj = bpy.data.objects.get(target_name)

        objects_to_remove = [cam_obj]
        if path_obj:
            objects_to_remove.append(path_obj)
        if target_obj:
            objects_to_remove.append(target_obj)

        try:
            for obj in objects_to_remove:
                bpy.data.objects.remove(obj, do_unlink=True)
            self.report({'INFO'}, f"Successfully deleted '{cam_name}' and its associated objects.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to delete camera objects: {e}")
            return {'CANCELLED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

class ArrangeScheduleTexts(bpy.types.Operator):
    bl_idname = "bim.arrange_schedule_texts"
    bl_label = "Auto-Arrange Schedule Texts"
    bl_options = {"REGISTER", "UNDO"}

    arrangement: bpy.props.EnumProperty(
        name="Arrangement",
        items=[
            ('VERTICAL', "Vertical Stack", "Stack texts vertically"),
            ('HORIZONTAL', "Horizontal Line", "Arrange texts horizontally"),
            ('CORNER', "Corner HUD", "Position as HUD in corner"),
            ('CUSTOM', "Custom", "Keep current positions"),
        ],
        default='VERTICAL',
    )
    base_position: bpy.props.FloatVectorProperty(
        name="Base Position", size=3, default=(0, 10, 5), subtype='TRANSLATION'
    )
    spacing: bpy.props.FloatProperty(name="Spacing", default=1.0, min=0.1, max=5.0)
    def execute(self, context):

            collection = bpy.data.collections.get("Schedule_Display_Texts")
            if not collection:
                self.report({'WARNING'}, "No schedule texts found")
                return {'CANCELLED'}
            order = ["Schedule_Date", "Schedule_Week", "Schedule_Day_Counter", "Schedule_Progress"]
            for i, name in enumerate(order):
                text_obj = collection.objects.get(name)
                if not text_obj:
                    continue
                if self.arrangement == 'VERTICAL':
                    text_obj.location = (self.base_position[0], self.base_position[1], self.base_position[2] - (i * self.spacing))
                elif self.arrangement == 'HORIZONTAL':
                    text_obj.location = (self.base_position[0] + (i * self.spacing * 3), self.base_position[1], self.base_position[2])
                elif self.arrangement == 'CORNER':
                    text_obj.location = (-8 + (i % 2) * 4, 10, 5 - (i // 2) * 1.5)
            self.report({'INFO'}, "Texts arranged successfully")
            return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
# Ensure name is exported for registration tools
class InitializeProfileSystem(bpy.types.Operator):
    """Inicializa el sistema de perfiles y repara datos corruptos"""
    bl_idname = "bim.initialize_profile_system"
    bl_label = "Initialize Profile System"
    bl_description = "Initialize and repair the profile assignment system"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            # 1. Asegurar que DEFAULT existe
            UnifiedProfileManager.ensure_default_group(context)

            # 2. Inicializar asignaciones para todas las tareas
            tprops = tool.Sequence.get_task_tree_props()
            initialized_count = 0

            for task_item in tprops.tasks:
                try:
                    # Asegurar que tiene la estructura de profile_group_choices
                    if not hasattr(task_item, 'profile_group_choices'):
                        continue

                    # Sincronizar con DEFAULT
                    UnifiedProfileManager.sync_default_group_to_predefinedtype(context, task_item)
                    initialized_count += 1

                except Exception as e:
                    print(f"Error initializing task {task_item.ifc_definition_id}: {e}")
                    continue

            self.report({'INFO'}, f"Profile system initialized. {initialized_count} tasks processed.")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to initialize profile system: {e}")
            return {'CANCELLED'}

# === Clean registration overrides (appended by patch) ===

class SetupTextHUD(bpy.types.Operator):
    bl_idname = "bim.setup_text_hud"
    bl_label = "Setup Text HUD"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        try:
            active_camera = context.scene.camera
            if not active_camera:
                self.report({'ERROR'}, "No active camera found")
                return {'CANCELLED'}

            collection = bpy.data.collections.get("Schedule_Display_Texts")
            if not collection:
                self.report({'WARNING'}, "No schedule texts found")
                return {'CANCELLED'}

            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # Configurar cada texto como HUD
            text_objects = self._get_ordered_text_objects(collection)

            for i, text_obj in enumerate(text_objects):
                if text_obj:
                    self._setup_text_as_hud(text_obj, active_camera, i, camera_props)

            self.report({'INFO'}, f"HUD configured for {len([t for t in text_objects if t])} text objects")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to setup HUD: {e}")
            return {'CANCELLED'}

    def _get_ordered_text_objects(self, collection):
        """Obtiene los objetos de texto en el orden correcto"""
        order = ["Schedule_Date", "Schedule_Week", "Schedule_Day_Counter", "Schedule_Progress"]
        return [collection.objects.get(name) for name in order]

def _setup_text_as_hud(self, text_obj, camera, index, camera_props):
    """Configura un objeto de texto individual como HUD"""
    import mathutils

    # Limpiar restricciones HUD existentes para evitar duplicados
    for c in list(text_obj.constraints):
        if "HUD" in c.name:
            text_obj.constraints.remove(c)

    # 1. Child Of constraint para seguir a la cámara PERO SIN ROTAR
    child_constraint = text_obj.constraints.new(type='CHILD_OF')
    child_constraint.name = "HUD_Follow_Camera"
    child_constraint.target = camera

    # --- CORRECCIÓN CLAVE ---
    # Habilitar solo la ubicación, deshabilitar la rotación y escala
    for axis in ('x', 'y', 'z'):
        setattr(child_constraint, f'use_location_{axis}', True)
        setattr(child_constraint, f'use_rotation_{axis}', False)  # <- IMPORTANTE
        setattr(child_constraint, f'use_scale_{axis}', False)

    # Es crucial "Set Inverse" para que el texto no salte a la posición de la cámara
    try:
        child_constraint.inverse_matrix = camera.matrix_world.inverted()
    except Exception:
        pass

    # 2. Calcular posición local relativa a la cámara (usará nuestro método mejorado)
    local_position = self._calculate_hud_position(camera, index, camera_props)
    text_obj.location = local_position

    # 3. Configurar escala
    self._update_text_scale(text_obj, camera, camera_props)

    # 4. Marcar como objeto HUD
    text_obj["is_hud_element"] = True
    text_obj["hud_index"] = int(index)

    print(f"✅ HUD configurado para {getattr(text_obj, 'name', '<text>')} en {local_position}")

def _get_aspect_ratio(self, scene):
    """Return render aspect ratio (width/height) including pixel aspect."""
    try:
        r = scene.render
        w = float(getattr(r, "resolution_x", 1920)) * float(getattr(r, "pixel_aspect_x", 1.0))
        h = float(getattr(r, "resolution_y", 1080)) * float(getattr(r, "pixel_aspect_y", 1.0))
        if h == 0:
            return 1.0
        return max(0.0001, w / h)
    except Exception:
        return 1.0

def _calculate_hud_position(self, camera, index, camera_props):
    """Calcula la posición local del HUD relativa a la cámara usando el sensor."""
    import mathutils
    scene = bpy.context.scene
    cam_data = camera.data
    aspect = self._get_aspect_ratio(scene)

    # Distancia de referencia en el eje -Z local de la cámara
    distance_plane = -10.0

    if cam_data.type == 'PERSP':
        # Basado en tamaño de sensor y distancia focal
        sensor_width = float(getattr(cam_data, "sensor_width", 36.0))
        focal_length = float(getattr(cam_data, "lens", 50.0))
        view_width_at_dist = (sensor_width / max(0.001, focal_length)) * abs(distance_plane)
        view_height_at_dist = view_width_at_dist / (aspect if aspect else 1.0)
    else:  # ORTHO
        view_height_at_dist = float(getattr(cam_data, "ortho_scale", 10.0))
        view_width_at_dist = view_height_at_dist * (aspect if aspect else 1.0)

    # Márgenes y espaciado
    margin_h = view_width_at_dist * float(getattr(camera_props, "hud_margin_horizontal", 0.05))
    margin_v = view_height_at_dist * float(getattr(camera_props, "hud_margin_vertical", 0.05))
    spacing  = view_height_at_dist * float(getattr(camera_props, "hud_text_spacing", 0.08))

    pos = str(getattr(camera_props, "hud_position", "TOP_LEFT"))

    if pos == 'TOP_LEFT':
        base_x = -view_width_at_dist / 2.0 + margin_h
        base_y =  view_height_at_dist / 2.0 - margin_v
    elif pos == 'TOP_RIGHT':
        base_x =  view_width_at_dist / 2.0 - margin_h
        base_y =  view_height_at_dist / 2.0 - margin_v
    elif pos == 'BOTTOM_LEFT':
        base_x = -view_width_at_dist / 2.0 + margin_h
        base_y = -view_height_at_dist / 2.0 + margin_v
    else:  # 'BOTTOM_RIGHT'
        base_x =  view_width_at_dist / 2.0 - margin_h
        base_y = -view_height_at_dist / 2.0 + margin_v

    if pos.startswith('TOP'):
        pos_y = base_y - (int(index) * spacing)
    else:
        pos_y = base_y + (int(index) * spacing)

    return mathutils.Vector((base_x, pos_y, distance_plane))

    def _update_text_scale(self, text_obj, camera, camera_props):
        """Actualiza la escala del texto basada en un factor configurable."""
        try:
            base_scale = 0.5 * float(getattr(camera_props, "hud_scale_factor", 1.0))
        except Exception:
            base_scale = 0.5
        text_obj.scale = (base_scale, base_scale, base_scale)

class ClearTextHUD(bpy.types.Operator):
    """Limpia las restricciones HUD de los textos"""
    bl_idname = "bim.clear_text_hud"
    bl_label = "Clear Text HUD"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            collection = bpy.data.collections.get("Schedule_Display_Texts")
            if not collection:
                return {'FINISHED'}

            cleared_count = 0
            for text_obj in list(collection.objects):
                if text_obj.get("is_hud_element", False):
                    # Limpiar restricciones HUD
                    for constraint in list(text_obj.constraints):
                        if "HUD" in getattr(constraint, "name", ""):
                            try:
                                text_obj.constraints.remove(constraint)
                            except Exception:
                                pass

                    # Limpiar propiedades HUD
                    try:
                        if "is_hud_element" in text_obj:
                            del text_obj["is_hud_element"]
                        if "hud_index" in text_obj:
                            del text_obj["hud_index"]
                    except Exception:
                        pass

                    cleared_count += 1

            self.report({'INFO'}, f"HUD cleared from {cleared_count} text objects")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to clear HUD: {e}")
            return {'CANCELLED'}

class UpdateTextHUDPositions(bpy.types.Operator):
    """Actualiza las posiciones de los elementos HUD"""
    bl_idname = "bim.update_text_hud_positions"
    bl_label = "Update HUD Positions"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            active_camera = context.scene.camera
            if not active_camera:
                return {'CANCELLED'}

            collection = bpy.data.collections.get("Schedule_Display_Texts")
            if not collection:
                return {'CANCELLED'}

            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            setup_operator = SetupTextHUD()

            for text_obj in list(collection.objects):
                if text_obj.get("is_hud_element", False):
                    index = int(text_obj.get("hud_index", 0))
                    local_position = setup_operator._calculate_hud_position(
                        active_camera, index, camera_props
                    )
                    try:
                        text_obj.location = local_position
                    except Exception:
                        text_obj.location = (float(local_position.x), float(local_position.y), float(local_position.z))

            return {'FINISHED'}

        except Exception as e:
            print(f"Error updating HUD positions: {e}")
            return {'CANCELLED'}

class UpdateTextHUDScale(bpy.types.Operator):
    """Actualiza la escala de los elementos HUD"""
    bl_idname = "bim.update_text_hud_scale"
    bl_label = "Update HUD Scale"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            active_camera = context.scene.camera
            if not active_camera:
                return {'CANCELLED'}

            collection = bpy.data.collections.get("Schedule_Display_Texts")
            if not collection:
                return {'CANCELLED'}

            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            setup_operator = SetupTextHUD()

            for text_obj in list(collection.objects):
                if text_obj.get("is_hud_element", False):
                    setup_operator._update_text_scale(text_obj, active_camera, camera_props)

            return {'FINISHED'}

        except Exception as e:
            print(f"Error updating HUD scale: {e}")
            return {'CANCELLED'}

class ToggleTextHUD(bpy.types.Operator):
    """Botón para activar/desactivar el HUD de textos"""
    bl_idname = "bim.toggle_text_hud"
    bl_label = "Toggle Text HUD"
    bl_description = "Enable/disable text HUD attachment to active camera"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # Toggle del estado
            camera_props.enable_text_hud = not bool(camera_props.enable_text_hud)

            if camera_props.enable_text_hud:
                bpy.ops.bim.setup_text_hud()
                self.report({'INFO'}, "Text HUD enabled")
            else:
                bpy.ops.bim.clear_text_hud()
                self.report({'INFO'}, "Text HUD disabled")

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle HUD: {e}")
            return {'CANCELLED'}

# ==============================
# OPERADORES HUD GPU
# ==============================

class EnableScheduleHUD(bpy.types.Operator):
    """Activa el HUD GPU para mostrar información del cronograma"""
    bl_idname = "bim.enable_schedule_hud"
    bl_label = "Enable Schedule HUD"
    bl_description = "Enable GPU-based HUD overlay for schedule information"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            print("🟢 Starting HUD enable process...")

            # 1. Obtener las propiedades de animación y cámara
            import bonsai.tool as tool
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # 2. Asegurar que la propiedad de habilitación esté en True
            if not camera_props.enable_text_hud:
                camera_props.enable_text_hud = True
                print("🔧 HUD property enabled")

            # 3. Registrar el handler
            from . import hud_overlay

            if not hud_overlay.is_hud_enabled():
                print("🔧 Registering HUD handler...")
                hud_overlay.register_hud_handler()
            else:
                print("🔧 HUD handler already registered")

            # 4. Debug del estado
            hud_overlay.debug_hud_state()

            # 5. Refrescar
            hud_overlay.refresh_hud()

            self.report({'INFO'}, "Schedule HUD enabled")
            return {'FINISHED'}

        except Exception as e:
            print(f"🔴 Error enabling HUD: {e}")
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Failed to enable HUD: {e}")
            return {'CANCELLED'}

class DisableScheduleHUD(bpy.types.Operator):
    """Desactiva el HUD GPU"""
    bl_idname = "bim.disable_schedule_hud"
    bl_label = "Disable Schedule HUD"
    bl_description = "Disable GPU-based HUD overlay"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            print("🔴 Disabling HUD...")

            # 1. Obtener las propiedades de animación y cámara
            import bonsai.tool as tool
            anim_props = tool.Sequence.get_animation_props()
            camera_props = anim_props.camera_orbit

            # 2. Asegurar que la propiedad de habilitación esté en False
            if camera_props.enable_text_hud:
                camera_props.enable_text_hud = False
                print("🔧 HUD property disabled")

            # 3. Desregistrar handler
            from . import hud_overlay
            hud_overlay.unregister_hud_handler()

            # 4. Forzar redibujado
            for area in context.screen.areas:
                if getattr(area, "type", None) == 'VIEW_3D':
                    area.tag_redraw()

            self.report({'INFO'}, "Schedule HUD disabled")
            return {'FINISHED'}

        except Exception as e:
            print(f"🔴 Error disabling HUD: {e}")
            self.report({'ERROR'}, f"Failed to disable HUD: {e}")
            return {'CANCELLED'}

class ToggleScheduleHUD(bpy.types.Operator):
    """Alterna el estado del HUD GPU"""
    bl_idname = "bim.toggle_schedule_hud"
    bl_label = "Toggle Schedule HUD"
    bl_description = "Toggle GPU-based HUD overlay on/off"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import hud_overlay  # Import relativo del módulo de overlay GPU

            if hud_overlay.is_hud_enabled():
                bpy.ops.bim.disable_schedule_hud()
            else:
                bpy.ops.bim.enable_schedule_hud()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle HUD: {e}")
            return {'CANCELLED'}

class RefreshScheduleHUD(bpy.types.Operator):
    """Refresca el HUD GPU con redibujado forzado"""
    bl_idname = "bim.refresh_schedule_hud"
    bl_label = "Refresh HUD"
    bl_description = "Refresh HUD display and settings with forced redraw"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import hud_overlay

            # Refrescar configuración del HUD
            hud_overlay.refresh_hud()

            # Forzar redibujado de todas las áreas 3D
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

            return {'FINISHED'}
        except Exception as e:
            print(f"HUD refresh error: {e}")
            return {'CANCELLED'}

class DebugScheduleHUD(bpy.types.Operator):
    """Operador de diagnóstico para el HUD"""
    bl_idname = "bim.debug_schedule_hud"
    bl_label = "Debug Schedule HUD"
    bl_description = "Run diagnostic checks on the HUD system"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import hud_overlay
            hud_overlay.debug_hud_state()

            # Verificar contexto actual
            print("🔍 Current context check:")
            print(f"  Area type: {getattr(context.area, 'type', 'None')}")
            print(f"  Region: {context.region}")
            print(f"  Space data: {getattr(context, 'space_data', 'None')}")

            if context.region:
                print(f"  Viewport size: {context.region.width}x{context.region.height}")

            # Forzar un dibujado de prueba
            try:
                hud_overlay.schedule_hud.draw()
                print("✅ Test draw completed")
            except Exception as e:
                print(f"❌ Test draw failed: {e}")

            self.report({'INFO'}, "HUD debug completed - check console")
            return {'FINISHED'}

        except Exception as e:
            print(f"🔴 Debug failed: {e}")
            self.report({'ERROR'}, f"Debug failed: {e}")
            return {'CANCELLED'}

class TestScheduleHUD(bpy.types.Operator):
    """Operador de prueba para verificar el HUD"""
    bl_idname = "bim.test_schedule_hud"
    bl_label = "Test Schedule HUD"
    bl_description = "Test HUD functionality with sample data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            from . import hud_overlay

            # Verificar si está habilitado
            if not hud_overlay.is_hud_enabled():
                self.report({'WARNING'}, "HUD is not enabled. Enable it first.")
                return {'CANCELLED'}

            # Simular datos de prueba
            print("🧪 Testing HUD with sample data...")

            # Forzar redibujado múltiple
            for i in range(3):
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

            self.report({'INFO'}, "HUD test completed")
            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Test failed: {e}")
            return {'CANCELLED'}

class SetupHUDCompositor(bpy.types.Operator):
    bl_idname = "bim.setup_hud_compositor"
    bl_label = "Setup HUD Compositor"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        from . import hud_compositor
        if hud_compositor.hud_compositor_instance and hud_compositor.hud_compositor_instance.setup_compositor_hud(context.scene):
            hud_compositor.register_compositor_handler()
            self.report({'INFO'}, "Compositor HUD configured.")
            return {'FINISHED'}
        self.report({'ERROR'}, "Failed to configure compositor HUD.")
        return {'CANCELLED'}

class RemoveHUDCompositor(bpy.types.Operator):
    bl_idname = "bim.remove_hud_compositor"
    bl_label = "Remove HUD Compositor"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        from . import hud_compositor
        scene = context.scene
        if scene.use_nodes:
            if hud_compositor.hud_compositor_instance:
                hud_compositor.hud_compositor_instance.cleanup_hud_nodes(scene.node_tree)

        collection = bpy.data.collections.get("HUD_Schedule_Objects")
        if collection:
            for obj in list(collection.objects): bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(collection)

        hud_compositor.unregister_compositor_handler()
        self.report({'INFO'}, "HUD removed from compositor.")
        return {'FINISHED'}
# _try_register(ToggleTextHUD)

# --- Bind HUD helper functions to operator classes (safe even on re-register) ---
try:
    SetupTextHUD._setup_text_as_hud = _setup_text_as_hud
    SetupTextHUD._get_aspect_ratio = _get_aspect_ratio
    SetupTextHUD._calculate_hud_position = _calculate_hud_position
    SetupTextHUD._update_text_scale = _update_text_scale
except Exception:
    pass

try:
    UpdateTextHUDPositions._calculate_hud_position = _calculate_hud_position
except Exception:
    pass

try:
    UpdateTextHUDScale._update_text_scale = _update_text_scale
except Exception:
    pass

# ===============================
# NEW SNAPSHOT & CAMERA OPERATORS
# (Inserted by auto-fix on 2025-08-19)
# ===============================

class AddSnapshotCamera(bpy.types.Operator):
    """Add a static camera for snapshot viewing"""
    bl_idname = "bim.add_snapshot_camera"
    bl_label = "Add Snapshot Camera"
    bl_description = "Create a new static camera positioned for snapshot viewing"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            # Create camera data and object
            cam_data = bpy.data.cameras.new(name="Snapshot_Camera")
            cam_obj = bpy.data.objects.new(name="Snapshot_Camera", object_data=cam_data)
            # Link to scene
            context.collection.objects.link(cam_obj)
            # Position camera with a good default view
            cam_obj.location = (10, -10, 8)
            cam_obj.rotation_euler = (1.1, 0.0, 0.785)
            # Configure camera settings
            cam_data.lens = 50
            cam_data.clip_start = 0.1
            cam_data.clip_end = 1000
            # Set as active camera
            context.scene.camera = cam_obj
            # Select the camera
            bpy.ops.object.select_all(action='DESELECT')
            cam_obj.select_set(True)
            context.view_layer.objects.active = cam_obj
            self.report({'INFO'}, f"Snapshot camera '{cam_obj.name}' created and set as active")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to create snapshot camera: {str(e)}")
            return {'CANCELLED'}
class AlignSnapshotCameraToView(bpy.types.Operator):
    """Align snapshot camera to current 3D viewport view"""
    bl_idname = "bim.align_snapshot_camera_to_view"
    bl_label = "Align Snapshot Camera to View"
    bl_description = "Align the snapshot camera to match the current 3D viewport view"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Must have an active camera and a 3D viewport
        if not getattr(context.scene, "camera", None):
            return False
        if not getattr(context, "screen", None):
            return False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                return True
        return False

    def execute(self, context):
        try:
            cam_obj = context.scene.camera
            if not cam_obj:
                self.report({'ERROR'}, "No active camera in scene")
                return {'CANCELLED'}

            # Find the active 3D viewport
            rv3d = None
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    rv3d = area.spaces.active.region_3d
                    break
            if not rv3d:
                self.report({'ERROR'}, "No active 3D viewport found")
                return {'CANCELLED'}

            # Align camera to viewport view
            cam_obj.matrix_world = rv3d.view_matrix.inverted()

            # Ensure camera is static
            if getattr(cam_obj, "animation_data", None):
                cam_obj.animation_data_clear()
            for constraint in list(cam_obj.constraints):
                cam_obj.constraints.remove(constraint)

            self.report({'INFO'}, f"Snapshot camera '{cam_obj.name}' aligned to current view")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Failed to align snapshot camera: {str(e)}")
            return {'CANCELLED'}

# Enhanced snapshot with profiles and robust error handling
class SnapshotWithProfilesFixed(tool.Ifc.Operator, bpy.types.Operator):
    bl_idname = "bim.snapshot_with_profiles_fixed"
    bl_label = "Create Snapshot (Enhanced)"
    bl_description = "Create snapshot with enhanced error handling and profile management"
    bl_options = {"REGISTER", "UNDO"}

    def _execute(self, context):
        try:
            # Ensure default group exists
            try:
                if 'UnifiedProfileManager' in globals():
                    UnifiedProfileManager.ensure_default_group(context)  # type: ignore[name-defined]
            except Exception as e:
                print(f"Warning: Could not ensure default group: {e}")

            ws_props = tool.Sequence.get_work_schedule_props()
            anim_props = tool.Sequence.get_animation_props()

            # Validate work schedule
            ws_id = getattr(ws_props, "active_work_schedule_id", None)
            if not ws_id:
                self.report({'ERROR'}, "No active Work Schedule selected")
                return {'CANCELLED'}
            work_schedule = tool.Ifc.get().by_id(ws_id)
            if not work_schedule:
                self.report({'ERROR'}, "Active Work Schedule not found in IFC")
                return {'CANCELLED'}

            # Get settings with error handling
            try:
                settings = _get_animation_settings(context)
            except Exception as e:
                settings = {
                    "start": getattr(ws_props, "visualisation_start", None),
                    "finish": getattr(ws_props, "visualisation_finish", None),
                    "start_frame": getattr(context.scene, "frame_start", 1),
                    "total_frames": max(1, getattr(context.scene, "frame_end", 250) - getattr(context.scene, "frame_start", 1)),
                }
                print(f"Using fallback settings due to error: {e}")

            # Current frame
            cur_frame = getattr(context.scene, "frame_current", settings.get("start_frame", 1))

            # Compute product frames
            try:
                product_frames = _compute_product_frames(context, work_schedule, settings)
            except Exception as e:
                self.report({'ERROR'}, f"Computing frames failed: {e}")
                return {'CANCELLED'}

            # Determine snapshot group
            snap_group = "DEFAULT"
            try:
                # Try animation stack first
                if hasattr(anim_props, 'animation_group_stack'):
                    for item in anim_props.animation_group_stack:
                        if getattr(item, 'enabled', False) and getattr(item, 'group', None):
                            snap_group = item.group
                            break
                # Fallback to UI-selected group
                if snap_group == "DEFAULT":
                    snap_group = getattr(anim_props, 'profile_groups', 'DEFAULT') or 'DEFAULT'
                print(f"🔸 Snapshot using profile group: '{snap_group}'")
                # Sync if the active group matches
                if snap_group == getattr(anim_props, 'profile_groups', None):
                    try:
                        tool.Sequence.sync_active_group_to_json()
                    except Exception as sync_error:
                        print(f"Warning: Could not sync group: {sync_error}")
            except Exception as group_error:
                print(f"Warning: Group determination failed, using DEFAULT: {group_error}")
                snap_group = 'DEFAULT'

            # Cache original colors
            original_colors = {}
            for obj in bpy.data.objects:
                if getattr(obj, "type", None) == 'MESH':
                    try:
                        original_colors[obj.name] = list(obj.color)
                    except Exception:
                        original_colors[obj.name] = [1.0, 1.0, 1.0, 1.0]

            # Apply snapshot states
            applied = 0
            errors = 0
            for obj in bpy.data.objects:
                try:
                    element = tool.Ifc.get_entity(obj)
                    if not element:
                        continue
                    # Hide spaces
                    try:
                        if hasattr(element, "is_a") and element.is_a("IfcSpace"):
                            obj.hide_viewport = True
                            obj.hide_render = True
                            continue
                    except Exception:
                        pass

                    pid = None
                    try:
                        pid = element.id() if hasattr(element, "id") else None
                    except Exception:
                        pid = None
                    if pid is None or pid not in product_frames:
                        continue

                    original_color = original_colors.get(obj.name, [1.0, 1.0, 1.0, 1.0])
                    frames_list = product_frames[pid]

                    # Find appropriate frame data for current frame
                    frame_data = None
                    for fd in frames_list:
                        states = fd.get("states", {})
                        for state_name, (start, end) in states.items():
                            if start <= cur_frame <= end:
                                frame_data = fd
                                break
                        if frame_data:
                            break
                    if not frame_data:
                        frame_data = frames_list[0] if frames_list else None
                    if not frame_data:
                        continue

                    # Resolve task and profile
                    task = frame_data.get("task") or tool.Ifc.get().by_id(frame_data.get("task_id", 0))
                    profile = None
                    try:
                        if task:
                            profile = tool.Sequence.get_assigned_profile_for_task(task, anim_props, snap_group)
                    except Exception:
                        profile = None
                    if not profile:
                        try:
                            predefined_type = getattr(task, 'PredefinedType', 'NOTDEFINED') if task else 'NOTDEFINED'
                            profile = tool.Sequence.load_profile_from_group(snap_group, predefined_type)
                        except Exception:
                            profile = None
                    if not profile:
                        try:
                            predefined_type = getattr(task, 'PredefinedType', 'NOTDEFINED') if task else 'NOTDEFINED'
                            profile = tool.Sequence.create_generic_profile(predefined_type)
                        except Exception:
                            continue

                    # Determine state
                    state = "end"
                    states = frame_data.get("states", {})
                    for state_name, (start, end) in states.items():
                        if start <= cur_frame <= end:
                            if state_name in ("before_start", "start"):
                                state = "start"
                            elif state_name == "active":
                                state = "in_progress"
                            else:
                                state = "end"
                            break

                    # Apply state
                    self._apply_profile_state(obj, profile, state, original_color, frame_data)
                    applied += 1
                except Exception as obj_error:
                    errors += 1
                    print(f"Error processing object {getattr(obj, 'name', '<unknown>')}: {obj_error}")
                    continue

            # Ensure object color shading
            try:
                area = tool.Blender.get_view3d_area()
                if area and area.spaces:
                    area.spaces[0].shading.color_type = "OBJECT"
            except Exception:
                pass

            message = f"Snapshot applied to {applied} objects using group '{snap_group}' at frame {cur_frame}"
            if errors > 0:
                message += f" ({errors} errors)"
            self.report({'INFO'}, message)
            return {'FINISHED'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Snapshot failed: {str(e)}")
            return {'CANCELLED'}

    def _apply_profile_state(self, obj, profile, state, original_color, frame_data):
        """Apply profile state to object with error handling"""
        try:
            # Consider toggles
            if state == "start" and not getattr(profile, "consider_start", True):
                if frame_data.get("relationship") == "output":
                    obj.hide_viewport = True
                    obj.hide_render = True
                return
            if state == "in_progress" and not getattr(profile, "consider_active", True):
                return
            if state == "end" and not getattr(profile, "consider_end", True):
                return

            # Determine color and visibility
            if state == "start":
                color = original_color if getattr(profile, "use_start_original_color", False) else getattr(profile, "start_color", [1, 1, 1, 1])
            elif state == "in_progress":
                color = original_color if getattr(profile, "use_active_original_color", False) else getattr(profile, "in_progress_color", [0, 1, 0, 1])
            else:  # end
                if getattr(profile, "use_end_original_color", False):
                    color = original_color
                elif getattr(profile, "hide_at_end", False):
                    obj.hide_viewport = True
                    obj.hide_render = True
                    return
                else:
                    color = getattr(profile, "end_color", [0.7, 0.7, 0.7, 1])

            obj.color = color
            obj.hide_viewport = False
            obj.hide_render = False
        except Exception as e:
            print(f"Error applying profile state: {e}")
            obj.hide_viewport = False
            obj.hide_render = False



class RefreshTaskOutputCounts(bpy.types.Operator):
    """Recalcula el número de 'Outputs' para todas las tareas en la lista."""
    bl_idname = "bim.refresh_task_output_counts"
    bl_label = "Refresh Output Counts"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            # Llama a la función centralizada en sequence.py
            core.refresh_task_output_counts(tool.Sequence)
            self.report({'INFO'}, "Recuentos de 'Outputs' actualizados.")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to refrescar: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


# === INICIO CÓDIGO PARA FILTROS (operators) ===
class AddTaskFilter(bpy.types.Operator):
    """Añade una nueva regla de filtro a la lista."""
    bl_idname = "bim.add_task_filter"
    bl_label = "Add Task Filter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        new_rule = props.filters.rules.add()
        # Inicializa data_type/operadores de la nueva regla
        update_filter_column(new_rule, context)
        # valor por defecto útil
        try:
            new_rule.column = "IfcTask.Name"
        except Exception:
            pass
        props.filters.active_rule_index = len(props.filters.rules) - 1
        return {'FINISHED'}

class RemoveTaskFilter(bpy.types.Operator):
    """Elimina la regla de filtro seleccionada."""
    bl_idname = "bim.remove_task_filter"
    bl_label = "Remove Task Filter"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        index = props.filters.active_rule_index
        if 0 <= index < len(props.filters.rules):
            props.filters.rules.remove(index)
            props.filters.active_rule_index = min(max(0, index - 1), len(props.filters.rules) - 1)
        return {'FINISHED'}

class ApplyTaskFilters(bpy.types.Operator):
    """Dispara el recálculo y la actualización de la lista de tareas."""
    bl_idname = "bim.apply_task_filters"
    bl_label = "Apply Task Filters"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        work_schedule = tool.Sequence.get_active_work_schedule()
        if work_schedule:
            tool.Sequence.load_task_tree(work_schedule)
            tool.Sequence.load_task_properties()
        return {'FINISHED'}
# === FIN CÓDIGO PARA FILTROS (operators) ===


# === INICIO CÓDIGO PARA GUARDAR/CARGAR FILTROS ===



class UpdateSavedFilterSet(bpy.types.Operator):
    """Overwrites a saved filter set with the current active filter rules."""
    bl_idname = "bim.update_saved_filter_set"
    bl_label = "Update Saved Filter Set"
    bl_options = {"REGISTER", "UNDO"}

    set_index: bpy.props.IntProperty()


    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        saved_set = props.saved_filter_sets[self.set_index]

        # Clear old rules from the saved filter
        saved_set.rules.clear()

        # Copy current active rules to the saved filter
        for active_rule in props.filters.rules:
            saved_rule = saved_set.rules.add()
            saved_rule.is_active = active_rule.is_active
            saved_rule.column = active_rule.column
            saved_rule.operator = active_rule.operator
            saved_rule.value = active_rule.value

        self.report({'INFO'}, f"Filter '{saved_set.name}' updated successfully.")
        return {'FINISHED'}

class SaveFilterSet(bpy.types.Operator):
    """Guarda el conjunto de filtros actual como un preset con nombre."""
    bl_idname = "bim.save_filter_set"
    bl_label = "Save Filter Set"
    bl_options = {"REGISTER", "UNDO"}

    set_name: bpy.props.StringProperty(name="Name", description="Nombre para guardar este conjunto de filtros")

    def execute(self, context):
        if not self.set_name.strip():
            self.report({'ERROR'}, "El nombre no puede estar vacío.")
            return {'CANCELLED'}

        props = tool.Sequence.get_work_schedule_props()

        # Crear un nuevo conjunto guardado
        new_set = props.saved_filter_sets.add()
        new_set.name = self.set_name

        # Copiar las reglas del filtro activo al nuevo conjunto
        for active_rule in props.filters.rules:
            saved_rule = new_set.rules.add()
            saved_rule.is_active = active_rule.is_active
            saved_rule.column = active_rule.column
            saved_rule.operator = active_rule.operator
            saved_rule.value = active_rule.value

        self.report({'INFO'}, f"Filtro '{self.set_name}' guardado.")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class LoadFilterSet(bpy.types.Operator):
    """Carga un conjunto de filtros guardado y lo aplica."""
    bl_idname = "bim.load_filter_set"
    bl_label = "Load Filter Set"
    bl_options = {"REGISTER", "UNDO"}

    set_index: bpy.props.IntProperty()

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        if not (0 <= self.set_index < len(props.saved_filter_sets)):
            self.report({'ERROR'}, "Índice de filtro inválido.")
            return {'CANCELLED'}

        saved_set = props.saved_filter_sets[self.set_index]

        # Limpiar filtros activos y cargar los guardados
        props.filters.rules.clear()
        for saved_rule in saved_set.rules:
            active_rule = props.filters.rules.add()
            active_rule.is_active = saved_rule.is_active
            active_rule.column = saved_rule.column
            active_rule.operator = saved_rule.operator
            active_rule.value = saved_rule.value

        bpy.ops.bim.apply_task_filters()
        self.report({'INFO'}, f"Filtro '{saved_set.name}' cargado.")
        return {'FINISHED'}


class RemoveFilterSet(bpy.types.Operator):
    """Elimina un conjunto de filtros guardado."""
    bl_idname = "bim.remove_filter_set"
    bl_label = "Remove Filter Set"
    bl_options = {"REGISTER", "UNDO"}

    set_index: bpy.props.IntProperty()

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        if not (0 <= self.set_index < len(props.saved_filter_sets)):
            self.report({'ERROR'}, "Índice de filtro inválido.")
            return {'CANCELLED'}

        set_name = props.saved_filter_sets[self.set_index].name
        props.saved_filter_sets.remove(self.set_index)
        props.active_saved_filter_set_index = min(max(0, self.set_index - 1), len(props.saved_filter_sets) - 1)
        self.report({'INFO'}, f"Filtro '{set_name}' eliminado.")
        return {'FINISHED'}


class ExportFilterSet(bpy.types.Operator, ExportHelper):
    """Exports the ENTIRE library of saved filter sets to a JSON file."""
    bl_idname = "bim.export_filter_set"
    bl_label = "Export Filter Library"  # Updated label
    bl_description = "Export all saved filters to a single JSON file"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()

        # 1. Prepare a dictionary to store the entire library
        library_data = {}

        # 2. Iterate through each saved filter in the library
        for saved_set in props.saved_filter_sets:
            rules_data = []
            # 3. Iterate through rules of each saved filter
            for rule in saved_set.rules:
                rules_data.append({
                    "is_active": rule.is_active,
                    "column": rule.column,
                    "operator": rule.operator,
                    "value": rule.value,
                })
            # 4. Add the filter and its rules to the library
            library_data[saved_set.name] = {"rules": rules_data}

        # 5. Write the entire library to the JSON file
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(library_data, f, ensure_ascii=False, indent=4)

        self.report({'INFO'}, f"Filter library exported to {self.filepath}")
        return {'FINISHED'}

class ImportFilterSet(bpy.types.Operator, ImportHelper):
    """Imports a library of filter sets from a JSON file, replacing the current library."""
    bl_idname = "bim.import_filter_set"
    bl_label = "Import Filter Library"  # Updated label
    bl_description = "Import a filter library from a JSON file, replacing all current saved filters"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    # 'set_name' property is no longer needed; names come from the JSON file
    def execute(self, context):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                library_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Could not read or parse JSON file: {e}")
            return {'CANCELLED'}

        props = tool.Sequence.get_work_schedule_props()
        
        # 1. ELIMINADO: La línea `props.saved_filter_sets.clear()` ha sido removida.
        # Ya no se borra la biblioteca existente.
        
        # 2. AÑADIDO: Comprobación para evitar duplicados
        # Obtenemos los nombres de los filtros que ya existen.
        existing_names = {fs.name for fs in props.saved_filter_sets}
        imported_count = 0
        
        for set_name, set_data in library_data.items():
            # Si el nombre del filtro a importar ya existe, lo saltamos.
            if set_name in existing_names:
                continue

            # Si no existe, lo añadimos.
            new_set = props.saved_filter_sets.add()
            new_set.name = set_name
            
            for rule_data in set_data.get("rules", []):
                new_rule = new_set.rules.add()
                new_rule.is_active = rule_data.get("is_active", True)
                new_rule.column = rule_data.get("column", "")
                new_rule.operator = rule_data.get("operator", "CONTAINS")
                new_rule.value = rule_data.get("value", "")
            
            imported_count += 1
        
        self.report({'INFO'}, f"{imported_count} new filter sets imported and combined.")
        return {'FINISHED'}


# === INICIO DE CÓDIGO AÑADIDO ===

class FilterDatePicker(bpy.types.Operator):
    """Un Date Picker especializado que actualiza el valor de una regla de filtro."""
    bl_idname = "bim.filter_datepicker"
    bl_label = "Select Filter Date"
    bl_options = {"REGISTER", "UNDO"}

    # Propiedad para saber qué regla de la lista modificar
    rule_index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        props = tool.Sequence.get_work_schedule_props()
        if self.rule_index < 0 or self.rule_index >= len(props.filters.rules):
            self.report({'ERROR'}, "Invalid filter rule index.")
            return {'CANCELLED'}
        
        # Obtener la fecha seleccionada del DatePickerProperties
        selected_date_str = context.scene.DatePickerProperties.selected_date
        if not selected_date_str:
            self.report({'ERROR'}, "No date selected.")
            return {'CANCELLED'}
            
        # Actualizar el valor de la regla de filtro
        target_rule = props.filters.rules[self.rule_index]
        target_rule.value_string = selected_date_str
        
        # Aplicar los filtros automáticamente
        try:
            # bpy.ops.bim.apply_task_filters()  # <--- LÍNEA CORREGIDA (COMENTADA)
            pass  # No hacer nada automáticamente. El usuario aplicará los filtros manualmente.
        except Exception as e:
            print(f"Error applying filters: {e}")
        
        self.report({'INFO'}, f"Date set to: {selected_date_str}")
        return {"FINISHED"}

    def invoke(self, context, event):
        if self.rule_index < 0:
            self.report({'ERROR'}, "No rule index specified.")
            return {'CANCELLED'}
            
        props = tool.Sequence.get_work_schedule_props()
        if self.rule_index >= len(props.filters.rules):
            self.report({'ERROR'}, "Invalid filter rule index.")
            return {'CANCELLED'}
        
        # Obtener la fecha actual de la regla
        current_date_str = props.filters.rules[self.rule_index].value_string
        
        # Configurar el DatePickerProperties
        date_picker_props = context.scene.DatePickerProperties
        
        if current_date_str and current_date_str.strip():
            try:
                # Intentar parsear la fecha existente
                current_date = datetime.fromisoformat(current_date_str.split('T')[0])
            except Exception:
                try:
                    from dateutil import parser as date_parser
                    current_date = date_parser.parse(current_date_str)
                except Exception:
                    current_date = datetime.now()
        else:
            current_date = datetime.now()
        
        # Configurar las propiedades del DatePicker
        date_picker_props.selected_date = current_date.strftime("%Y-%m-%d")
        date_picker_props.display_date = current_date.replace(day=1).strftime("%Y-%m-%d")
        
        # Mostrar el diálogo
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        """Interfaz del calendario para seleccionar fechas"""
        import calendar
        from dateutil import relativedelta
        
        layout = self.layout
        props = context.scene.DatePickerProperties
        
        # Parsear la fecha de display actual
        try:
            display_date = datetime.fromisoformat(props.display_date)
        except Exception:
            display_date = datetime.now()
            props.display_date = display_date.strftime("%Y-%m-%d")
        
        # Campo de entrada manual de fecha
        row = layout.row()
        row.prop(props, "selected_date", text="Date")
        
        # Navegación del mes
        current_month = (display_date.year, display_date.month)
        lines = calendar.monthcalendar(*current_month)
        month_title = calendar.month_name[display_date.month] + f" {display_date.year}"
        
        # Header del mes con navegación
        row = layout.row(align=True)
        
        # Botón mes anterior
        prev_month = display_date - relativedelta.relativedelta(months=1)
        op = row.operator("wm.context_set_string", icon="TRIA_LEFT", text="")
        op.data_path = "scene.DatePickerProperties.display_date"
        op.value = prev_month.strftime("%Y-%m-%d")
        
        # Título del mes
        row.label(text=month_title)
        
        # Botón mes siguiente  
        next_month = display_date + relativedelta.relativedelta(months=1)
        op = row.operator("wm.context_set_string", icon="TRIA_RIGHT", text="")
        op.data_path = "scene.DatePickerProperties.display_date"
        op.value = next_month.strftime("%Y-%m-%d")
        
        # Días de la semana
        row = layout.row(align=True)
        for day_name in ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']:
            col = row.column(align=True)
            col.alignment = "CENTER"
            col.label(text=day_name)
        
        # Parsear la fecha seleccionada para resaltar
        try:
            selected_date = datetime.fromisoformat(props.selected_date)
        except Exception:
            selected_date = None
        
        # Días del calendario
        for week in lines:
            row = layout.row(align=True)
            for day in week:
                col = row.column(align=True)
                if day == 0:
                    col.label(text="")
                else:
                    day_date = datetime(display_date.year, display_date.month, day)
                    day_str = day_date.strftime("%Y-%m-%d")
                    
                    # Verificar si es el día seleccionado
                    is_selected = (selected_date and day_date.date() == selected_date.date())
                    
                    # Botón para seleccionar el día
                    op = col.operator("wm.context_set_string", 
                                    text=str(day), 
                                    depress=is_selected)
                    op.data_path = "scene.DatePickerProperties.selected_date"
                    op.value = day_str


# Solo registrar FilterDatePicker, NO las clases auxiliares
def register():
    try:
        bpy.utils.register_class(FilterDatePicker)
    except Exception as e:
        print(f"FilterDatePicker already registered or failed: {e}")

def unregister():
    try:
        bpy.utils.unregister_class(FilterDatePicker)
    except Exception as e:
        print(f"FilterDatePicker unregister failed: {e}")
