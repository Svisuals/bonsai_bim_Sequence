# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>, 2021-2022 Yassine Oualid <yassine@sigmadimensions.com>
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

import bpy
import bonsai.tool as tool
import ifcopenshell
import ifcopenshell.util.attribute
import ifcopenshell.util.date
from ifcopenshell.util.doc import get_predefined_type_doc
import json
from typing import Any


def refresh():
    SequenceData.is_loaded = False
    WorkPlansData.is_loaded = False
    TaskICOMData.is_loaded = False
    WorkScheduleData.is_loaded = False
    AnimationColorSchemeData.is_loaded = False


class SequenceData:
    data: dict[str, Any] = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.data = {
            "has_work_plans": cls.has_work_plans(),
            "has_work_schedules": cls.has_work_schedules(),
            "has_work_calendars": cls.has_work_calendars(),
            "schedule_predefined_types_enum": cls.schedule_predefined_types_enum(),
            "task_columns_enum": cls.task_columns_enum(),
            "task_time_columns_enum": cls.task_time_columns_enum(),
        }
        cls.load_work_plans()
        cls.load_work_schedules()
        cls.load_work_calendars()
        cls.load_work_times()
        cls.load_recurrence_patterns()
        cls.load_time_periods()
        cls.load_sequences()
        cls.load_lag_times()
        cls.load_task_times()
        cls.load_tasks()
        cls.is_loaded = True

    @classmethod
    def has_work_plans(cls):
        return bool(tool.Ifc.get().by_type("IfcWorkPlan"))

    @classmethod
    def has_work_calendars(cls):
        return bool(tool.Ifc.get().by_type("IfcWorkCalendar"))

    @classmethod
    def number_of_work_plans_loaded(cls):
        return len(tool.Ifc.get().by_type("IfcWorkPlan"))

    @classmethod
    def number_of_work_schedules_loaded(cls):
        return len(tool.Ifc.get().by_type("IfcWorkSchedule"))

    @classmethod
    def has_work_schedules(cls):
        return bool(tool.Ifc.get().by_type("IfcWorkSchedule"))

    @classmethod
    def load_work_plans(cls):
        cls.data["work_plans"] = {}
        for work_plan in tool.Ifc.get().by_type("IfcWorkPlan"):
            data = {"Name": work_plan.Name or "Unnamed"}
            data["IsDecomposedBy"] = []
            for rel in work_plan.IsDecomposedBy:
                data["IsDecomposedBy"].extend([o.id() for o in rel.RelatedObjects])
            cls.data["work_plans"][work_plan.id()] = data
        cls.data["number_of_work_plans_loaded"] = cls.number_of_work_plans_loaded()

    @classmethod
    def load_work_schedules(cls):
        cls.data["work_schedules"] = {}
        cls.data["work_schedules_enum"] = []
        for work_schedule in tool.Ifc.get().by_type("IfcWorkSchedule"):
            data = work_schedule.get_info()
            if not data["Name"]:
                data["Name"] = "Unnamed"
            del data["OwnerHistory"]
            if data["Creators"]:
                data["Creators"] = [p.id() for p in data["Creators"]]
            data["CreationDate"] = (
                ifcopenshell.util.date.ifc2datetime(data["CreationDate"]) if data["CreationDate"] else ""
            )
            data["StartTime"] = ifcopenshell.util.date.ifc2datetime(data["StartTime"]) if data["StartTime"] else ""
            data["FinishTime"] = ifcopenshell.util.date.ifc2datetime(data["FinishTime"]) if data["FinishTime"] else ""
            data["RelatedObjects"] = []
            for rel in work_schedule.Controls:
                for obj in rel.RelatedObjects:
                    if obj.is_a("IfcTask"):
                        data["RelatedObjects"].append(obj.id())
            cls.data["work_schedules"][work_schedule.id()] = data
            cls.data["work_schedules_enum"].append((str(work_schedule.id()), data["Name"], ""))

        cls.data["number_of_work_schedules_loaded"] = cls.number_of_work_schedules_loaded()

    @classmethod
    def load_work_calendars(cls):
        cls.data["work_calendars"] = {}
        cls.data["work_calendars_enum"] = []
        for work_calendar in tool.Ifc.get().by_type("IfcWorkCalendar"):
            data = work_calendar.get_info()
            del data["OwnerHistory"]
            if not data["Name"]:
                data["Name"] = "Unnamed"
            data["WorkingTimes"] = [t.id() for t in work_calendar.WorkingTimes or []]
            data["ExceptionTimes"] = [t.id() for t in work_calendar.ExceptionTimes or []]
            cls.data["work_calendars"][work_calendar.id()] = data
            cls.data["work_calendars_enum"].append((str(work_calendar.id()), data["Name"], ""))

        cls.data["number_of_work_calendars_loaded"] = len(cls.data["work_calendars"].keys())

    @classmethod
    def load_work_times(cls):
        cls.data["work_times"] = {}
        for work_time in tool.Ifc.get().by_type("IfcWorkTime"):
            data = work_time.get_info()
            if tool.Ifc.get_schema() == "IFC4X3":
                start_date, finish_date = data["StartDate"], data["FinishDate"]
            else:
                start_date, finish_date = data["Start"], data["Finish"]
            data["Start"] = ifcopenshell.util.date.ifc2datetime(start_date) if start_date else None
            data["Finish"] = ifcopenshell.util.date.ifc2datetime(finish_date) if finish_date else None
            data["RecurrencePattern"] = work_time.RecurrencePattern.id() if work_time.RecurrencePattern else None
            cls.data["work_times"][work_time.id()] = data

    @classmethod
    def load_recurrence_patterns(cls):
        cls.data["recurrence_patterns"] = {}
        for recurrence_pattern in tool.Ifc.get().by_type("IfcRecurrencePattern"):
            data = recurrence_pattern.get_info()
            data["TimePeriods"] = [t.id() for t in recurrence_pattern.TimePeriods or []]
            cls.data["recurrence_patterns"][recurrence_pattern.id()] = data

    @classmethod
    def load_sequences(cls):
        cls.data["sequences"] = {}
        for sequence in tool.Ifc.get().by_type("IfcRelSequence"):
            data = sequence.get_info()
            data["RelatingProcess"] = sequence.RelatingProcess.id()
            data["RelatedProcess"] = sequence.RelatedProcess.id()
            data["TimeLag"] = sequence.TimeLag.id() if sequence.TimeLag else None
            cls.data["sequences"][sequence.id()] = data

    @classmethod
    def load_time_periods(cls):
        cls.data["time_periods"] = {}
        for time_period in tool.Ifc.get().by_type("IfcTimePeriod"):
            cls.data["time_periods"][time_period.id()] = {
                "StartTime": ifcopenshell.util.date.ifc2datetime(time_period.StartTime),
                "EndTime": ifcopenshell.util.date.ifc2datetime(time_period.EndTime),
            }

    @classmethod
    def load_task_times(cls):
        cls.data["task_times"] = {}
        for task_time in tool.Ifc.get().by_type("IfcTaskTime"):
            data = task_time.get_info()
            for key, value in data.items():
                if not value:
                    continue
                if "Start" in key or "Finish" in key or key == "StatusTime":
                    data[key] = ifcopenshell.util.date.ifc2datetime(value)
                elif key == "ScheduleDuration":
                    data[key] = ifcopenshell.util.date.ifc2datetime(value)
            cls.data["task_times"][task_time.id()] = data

    @classmethod
    def load_lag_times(cls):
        cls.data["lag_times"] = {}
        for lag_time in tool.Ifc.get().by_type("IfcLagTime"):
            data = lag_time.get_info()
            if data["LagValue"]:
                if data["LagValue"].is_a("IfcDuration"):
                    data["LagValue"] = ifcopenshell.util.date.ifc2datetime(data["LagValue"].wrappedValue)
                else:
                    data["LagValue"] = float(data["LagValue"].wrappedValue)
            cls.data["lag_times"][lag_time.id()] = data

    @classmethod
    def load_tasks(cls):
        cls.data["tasks"] = {}
        for task in tool.Ifc.get().by_type("IfcTask"):
            data = task.get_info()
            del data["OwnerHistory"]
            data["HasAssignmentsWorkCalendar"] = []
            data["RelatedObjects"] = []
            data["Inputs"] = []
            data["Controls"] = []
            data["Outputs"] = []
            data["Resources"] = []
            data["IsPredecessorTo"] = []
            data["IsSuccessorFrom"] = []
            if task.TaskTime:
                data["TaskTime"] = data["TaskTime"].id()
            for rel in task.IsNestedBy:
                [data["RelatedObjects"].append(o.id()) for o in rel.RelatedObjects if o.is_a("IfcTask")]
            data["Nests"] = [r.RelatingObject.id() for r in task.Nests or []]
            [
                data["Outputs"].append(r.RelatingProduct.id())
                for r in task.HasAssignments
                if r.is_a("IfcRelAssignsToProduct")
            ]
            [
                data["Resources"].extend([o.id() for o in r.RelatedObjects if o.is_a("IfcResource")])
                for r in task.OperatesOn
            ]
            [
                data["Controls"].extend([o.id() for o in r.RelatedObjects if o.is_a("IfcControl")])
                for r in task.OperatesOn
            ]
            [data["Inputs"].extend([o.id() for o in r.RelatedObjects if o.is_a("IfcProduct")]) for r in task.OperatesOn]
            [data["IsPredecessorTo"].append(rel.id()) for rel in task.IsPredecessorTo or []]
            [data["IsSuccessorFrom"].append(rel.id()) for rel in task.IsSuccessorFrom or []]
            for rel in task.HasAssignments:
                if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl:
                    if rel.RelatingControl.is_a("IfcWorkCalendar"):
                        data["HasAssignmentsWorkCalendar"].append(rel.RelatingControl.id())
            data["NestingIndex"] = None
            for rel in task.Nests or []:
                data["NestingIndex"] = rel.RelatedObjects.index(task)
            cls.data["tasks"][task.id()] = data
    @classmethod
    def schedule_predefined_types_enum(cls) -> list[tuple[str, str, str]]:
        results: list[tuple[str, str, str]] = []
        declaration = tool.Ifc().schema().declaration_by_name("IfcWorkSchedule").as_entity()
        assert declaration
        version = tool.Ifc.get_schema()
        for attribute in declaration.attributes():
            if attribute.name() == "PredefinedType":
                results.extend(
                    [
                        (e, e, get_predefined_type_doc(version, "IfcWorkSchedule", e))
                        for e in ifcopenshell.util.attribute.get_enum_items(attribute)
                        if e != "BASELINE"
                    ]
                )
                break
        return results

    @classmethod
    def task_columns_enum(cls) -> list[tuple[str, str, str]]:
        schema = tool.Ifc.schema()
        taskcolumns_enum = []
        assert (entity := schema.declaration_by_name("IfcTask").as_entity())
        for a in entity.all_attributes():
            if (primitive_type := ifcopenshell.util.attribute.get_primitive_type(a)) not in (
                "string",
                "float",
                "integer",
                "boolean",
                "enum",
            ):
                continue
            taskcolumns_enum.append((f"{a.name()}/{primitive_type}", a.name(), ""))
        return taskcolumns_enum

    @classmethod
    def task_time_columns_enum(cls) -> list[tuple[str, str, str]]:
        schema = tool.Ifc.schema()
        tasktimecolumns_enum = []
        assert (entity := schema.declaration_by_name("IfcTaskTime").as_entity())
        for a in entity.all_attributes():
            if (primitive_type := ifcopenshell.util.attribute.get_primitive_type(a)) not in (
                "string",
                "float",
                "integer",
                "boolean",
                "enum",
            ):
                continue
            tasktimecolumns_enum.append((f"{a.name()}/{primitive_type}", a.name(), ""))
        return tasktimecolumns_enum


    @classmethod
    def load_product_task_relationships(cls, product_id):
        """
        Carga las relaciones de tareas para un producto específico.
        """
        try:
            if not tool.Ifc.get():
                return {"input_tasks": [], "output_tasks": []}
            product = tool.Ifc.get().by_id(product_id)
            if not product:
                return {"input_tasks": [], "output_tasks": []}
            
            # Usar el método corregido de Sequence
            input_tasks, output_tasks = tool.Sequence.get_tasks_for_product(product)
            
            def _to_dict(task):
                try:
                    return {"id": task.id(), "name": getattr(task, "Name", None) or "Unnamed"}
                except Exception:
                    return None
            
            inputs = [d for d in (_to_dict(t) for t in (input_tasks or [])) if d]
            outputs = [d for d in (_to_dict(t) for t in (output_tasks or [])) if d]
            
            return {
                "input_tasks": inputs,
                "output_tasks": outputs
            }
        except Exception as e:
            print(f"Error loading product task relationships: {e}")
            return {"input_tasks": [], "output_tasks": []}

class WorkScheduleData:
    data = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.data = {
            "can_have_baselines": cls.can_have_baselines(),
            "active_work_schedule_baselines": cls.active_work_schedule_baselines(),
        }
        cls.is_loaded = True

    @classmethod
    def can_have_baselines(cls) -> bool:
        props = tool.Sequence.get_work_schedule_props()
        if not props.active_work_schedule_id:
            return False
        return tool.Ifc.get().by_id(props.active_work_schedule_id).PredefinedType == "PLANNED"

    @classmethod
    def active_work_schedule_baselines(cls) -> list[dict[str, Any]]:
        results = []
        props = tool.Sequence.get_work_schedule_props()
        if not props.active_work_schedule_id:
            return []
        for rel in tool.Ifc.get().by_id(props.active_work_schedule_id).Declares:
            for work_schedule in rel.RelatedObjects:
                if work_schedule.PredefinedType == "BASELINE":
                    results.append(
                        {
                            "id": work_schedule.id(),
                            "name": work_schedule.Name or "Unnamed",
                            "date": str(ifcopenshell.util.date.ifc2datetime(work_schedule.CreationDate)),
                        }
                    )
        return results


class WorkPlansData:
    data = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.data = {
            "total_work_plans": cls.total_work_plans(),
            "work_plans": cls.work_plans(),
            "has_work_schedules": cls.has_work_schedules(),
            "active_work_plan_schedules": cls.active_work_plan_schedules(),
        }
        cls.is_loaded = True

    @classmethod
    def total_work_plans(cls):
        return len(tool.Ifc.get().by_type("IfcWorkPlan"))

    @classmethod
    def work_plans(cls):
        results = []
        for work_plan in tool.Ifc.get().by_type("IfcWorkPlan"):
            results.append({"id": work_plan.id(), "name": work_plan.Name or "Unnamed"})
        return results

    @classmethod
    def has_work_schedules(cls):
        return len(tool.Ifc.get().by_type("IfcWorkSchedule"))

    @classmethod
    def active_work_plan_schedules(cls):
        results = []
        props = tool.Sequence.get_work_plan_props()
        if not props.active_work_plan_id:
            return []
        for rel in tool.Ifc.get().by_id(props.active_work_plan_id).IsDecomposedBy:
            for work_schedule in rel.RelatedObjects:
                results.append({"id": work_schedule.id(), "name": work_schedule.Name or "Unnamed"})
        return results


class TaskICOMData:
    data = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.data = {"can_active_resource_be_assigned": cls.can_active_resource_be_assigned()}
        cls.is_loaded = True

    @classmethod
    def can_active_resource_be_assigned(cls) -> bool:
        props = tool.Resource.get_resource_props()
        active_resource = props.active_resource
        if active_resource:
            resource_id = active_resource.ifc_definition_id
            return not tool.Ifc.get().by_id(resource_id).is_a("IfcCrewResource")
        return False



class AnimationColorSchemeData:
    data = {}
    is_loaded = False

    @classmethod
    def load(cls):
        cls.is_loaded = True
        cls.data = {}
        # Be defensive: some older builds may miss methods or JSON structures
        try:
            cls.data["saved_color_schemes"] = cls.saved_color_schemes()
        except Exception:
            cls.data["saved_color_schemes"] = []
        try:
            cls.data["saved_appearance_profiles"] = cls.saved_appearance_profiles()
        except Exception:
            cls.data["saved_appearance_profiles"] = []

    @classmethod
    def saved_color_schemes(cls):
        import json
        results = []
        try:
            groups = tool.Ifc.get().by_type("IfcGroup")
        except Exception:
            groups = []
        for group in groups:
            try:
                data = json.loads(group.Description) if getattr(group, "Description", None) else None
                if (
                    isinstance(data, dict)
                    and data.get("type") == "BBIM_AnimationColorScheme"
                    and data.get("colourscheme")
                ):
                    results.append(group)
            except Exception:
                # Ignore malformed JSON or missing fields
                pass
        results_sorted = sorted(results, key=lambda x: x.Name or "Unnamed")
        return [(str(g.id()), g.Name or "Unnamed", "") for g in results_sorted]

    @classmethod
    def saved_appearance_profiles(cls):
        results = []
        try:
            for txt in bpy.data.texts:
                if txt.name.startswith("BIM_APROFILES_"):
                    name = txt.name.replace("BIM_APROFILES_", "", 1)
                    results.append((name, name, "Saved Appearance Profiles"))
        except Exception:
            pass
        results.sort(key=lambda x: x[0].lower())
        return results


# --- Helpers de estado y perfiles (compatibles con UnifiedProfileManager) ---
def interpolate_profile_values(profile, state, progress=0.0):
    """Interpola valores del perfil según progreso (0.0..1.0). Devuelve dict con 'alpha' si aplica."""
    try:
        # IMPORTANTE: Solo procesar transparencia activa si el estado es activo Y está considerado
        if state in ("active", "in_progress") and getattr(profile, "consider_active", True):
            start_alpha = float(getattr(profile, "active_start_transparency", 0.0) or 0.0)
            end_alpha = float(getattr(profile, "active_finish_transparency", start_alpha) or start_alpha)
            interp_type = float(getattr(profile, "active_transparency_interpol", 1.0) or 1.0)
            
            if interp_type < 0.5:  # Step
                alpha = start_alpha
            else:  # Linear
                progress = max(0.0, min(1.0, float(progress)))
                alpha = start_alpha + (end_alpha - start_alpha) * progress
            return {"alpha": alpha}
        
        # Para el estado start, verificar si debe considerarse
        elif state == "start" and getattr(profile, "consider_start", False):
            start_alpha = float(getattr(profile, "start_transparency", 0.0) or 0.0)
            return {"alpha": start_alpha}
            
    except Exception:
        pass
    return {}

def validate_profile_consistency(profile_data):
    """Valida consistencia de un dict de perfil. Retorna lista de errores (strings)."""
    errors = []
    # Colores
    for color_field in ("start_color", "in_progress_color", "end_color"):
        if color_field in profile_data:
            color = profile_data[color_field]
            if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
                errors.append(f"Invalid {color_field}: {color}")
            else:
                try:
                    vals = [float(v) for v in color]
                    if any(v < 0.0 or v > 1.0 for v in vals):
                        errors.append(f"Out-of-range {color_field}: {color}")
                except Exception:
                    errors.append(f"Non-numeric {color_field}: {color}")
    # Transparencias
    for alpha_field in ("start_transparency", "end_transparency", "active_start_transparency", "active_finish_transparency"):
        if alpha_field in profile_data:
            try:
                alpha = float(profile_data[alpha_field])
                if not 0.0 <= alpha <= 1.0:
                    errors.append(f"Invalid {alpha_field}: {alpha}")
            except Exception:
                errors.append(f"Non-numeric {alpha_field}: {profile_data[alpha_field]}")
    return errors


def validate_and_adjust_frame(frame, settings):
    """
    Valida y ajusta un frame para asegurar que esté dentro del rango válido.
    Evita frames negativos y fuera de rango.
    """
    start_frame = int(settings.get("start_frame", 1))
    total_frames = int(settings.get("total_frames", 250))
    end_frame = start_frame + total_frames
    
    # Asegurar que el frame no sea negativo
    if frame < start_frame:
        return start_frame
    
    # Asegurar que no exceda el final
    if frame > end_frame:
        return end_frame
    
    return int(frame)

def compute_task_frames(task, settings):
    """Versión mejorada con validación de frames"""
    start_date = ifcopenshell.util.sequence.derive_date(task, "ScheduleStart", is_earliest=True)
    finish_date = ifcopenshell.util.sequence.derive_date(task, "ScheduleFinish", is_latest=True)
    
    if not start_date or not finish_date:
        return None, None
    
    # Validar contra el rango de visualización
    viz_start = settings["start"]
    viz_finish = settings["finish"]
    
    # Si está completamente fuera del rango
    if finish_date < viz_start:
        # Tarea terminada antes del período
        return settings["start_frame"], settings["start_frame"]
    
    if start_date > viz_finish:
        # Tarea empieza después del período
        return None, None
    
    # Ajustar fechas al rango
    adjusted_start = max(start_date, viz_start)
    adjusted_finish = min(finish_date, viz_finish)
    
    # Calcular frames
    total_frames = int(settings["total_frames"])
    duration = settings["duration"]
    
    if duration.total_seconds() > 0:
        start_progress = (adjusted_start - viz_start) / duration
        finish_progress = (adjusted_finish - viz_start) / duration
    else:
        start_progress = 0
        finish_progress = 1
    
    start_frame = settings["start_frame"] + (start_progress * total_frames)
    finish_frame = settings["start_frame"] + (finish_progress * total_frames)
    
    # Validar y ajustar frames
    start_frame = validate_and_adjust_frame(start_frame, settings)
    finish_frame = validate_and_adjust_frame(finish_frame, settings)
    
    # Asegurar que start <= finish
    if start_frame > finish_frame:
        start_frame = finish_frame
    
    return int(start_frame), int(finish_frame)

def compute_progress_at_frame(task, frame, settings):
    """Devuelve progreso 0..1 de la tarea en un frame, o None si no aplica."""
    sf, ff = compute_task_frames(task, settings)
    if sf is None or ff is None or ff <= sf:
        return None
    if frame <= sf:
        return 0.0
    if frame >= ff:
        return 1.0
    return (float(frame) - float(sf)) / float(max(1, ff - sf))
