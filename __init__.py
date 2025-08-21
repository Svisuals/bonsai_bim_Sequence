# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
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

# pyright: reportAttributeAccessIssue=false

import bpy
from . import ui, prop, operator


classes = (
    # Operators from operator.py
    operator.AddSummaryTask,
    operator.AddTask,
    operator.AddTaskBars,
    operator.ClearTaskBars,
    operator.AddTaskColumn,
    operator.AddTimePeriod,
    operator.AddWorkCalendar,
    operator.AddWorkPlan,
    operator.AddWorkSchedule,
    operator.AddWorkTime,
    operator.AssignLagTime,
    operator.AssignPredecessor,
    operator.AssignProcess,
    operator.AssignProduct,
    operator.AssignRecurrencePattern,
    operator.AssignSuccessor,
    operator.AssignWorkSchedule,
    operator.Bonsai_DatePicker,
    operator.CalculateTaskDuration,
    operator.ClearPreviousAnimation,
    operator.ContractAllTasks,
    operator.ContractTask,
    operator.CopyTask,
    operator.CopyTaskAttribute,
    operator.CopyTaskCustomProfileGroup,
    operator.CopyWorkSchedule,
    operator.CreateBaseline,
    operator.ANIM_OT_group_stack_add,
    operator.ANIM_OT_group_stack_remove,
    operator.ANIM_OT_group_stack_move,
    operator.DisableEditingSequence,
    operator.DisableEditingTask,
    operator.DisableEditingTaskTime,
    operator.DisableEditingWorkCalendar,
    operator.DisableEditingWorkPlan,
    operator.DisableEditingWorkSchedule,
    operator.DisableEditingWorkTime,
    operator.EditSequenceAttributes,
    operator.EditSequenceTimeLag,
    operator.EditTask,
    operator.EditTaskCalendar,
    operator.EditTaskTime,
    operator.EditWorkCalendar,
    operator.EditWorkPlan,
    operator.EditWorkSchedule,
    operator.EditWorkTime,
    operator.EnableEditingSequenceAttributes,
    operator.EnableEditingSequenceTimeLag,
    operator.EnableEditingTask,
    operator.EnableEditingTaskCalendar,
    operator.EnableEditingTaskSequence,
    operator.EnableEditingTaskTime,
    operator.EnableEditingWorkCalendar,
    operator.EnableEditingWorkCalendarTimes,
    operator.EnableEditingWorkPlan,
    operator.EnableEditingWorkPlanSchedules,
    operator.EnableEditingWorkSchedule,
    operator.EnableEditingWorkScheduleTasks,
    operator.EnableEditingWorkTime,
    operator.ExpandAllTasks,
    operator.ExpandTask,
    operator.ExportMSP,
    operator.ExportP6,
    operator.GenerateGanttChart,
    operator.GuessDateRange,
    operator.GoToTask,
    operator.ImportWorkScheduleCSV,
    operator.SortWorkScheduleByIdAsc,  # added
    operator.ImportMSP,
    operator.ImportP6,
    operator.ImportP6XER,
    operator.ImportPP,
    operator.LoadAnimationColorScheme,
    operator.LoadDefaultAnimationColors,
    operator.LoadProductTasks,
    operator.LoadTaskProperties,
    operator.RecalculateSchedule,
    operator.RefreshTaskOutputCounts,
    operator.RemoveTask,
    operator.RemoveTaskCalendar,
    operator.RemoveTaskColumn,
    operator.RemoveTimePeriod,
    operator.RemoveWorkCalendar,
    operator.RemoveWorkPlan,
    operator.RemoveWorkSchedule,
    operator.RemoveWorkTime,
    operator.ReorderTask,
    operator.SaveAnimationColorScheme,
    operator.SaveAppearanceProfileSetInternal,
    operator.LoadAppearanceProfileSetInternal,
    operator.RemoveAppearanceProfileSetInternal,
    operator.SelectTaskRelatedInputs,
    operator.SelectTaskRelatedProducts,
    operator.SelectUnassignedWorkScheduleProducts,
    operator.SelectWorkScheduleProducts,
    operator.SetTaskSortColumn,
    operator.SetupDefaultTaskColumns,
    operator.UnassignLagTime,
    operator.UnassignPredecessor,
    operator.UnassignProcess,
    operator.UnassignProduct,
    operator.UnassignRecurrencePattern,
    operator.UnassignSuccessor,
    operator.UnassignWorkSchedule,
    # operator.VisualiseWorkScheduleDate,  # removed
    operator.SnapshotWithProfiles,

    # === NUEVOS OPERADORES PARA SNAPSHOT ===
    operator.AddSnapshotCamera,
    operator.AlignSnapshotCameraToView,
    operator.SnapshotWithProfilesFixed,

    operator.VisualiseWorkScheduleDateRange,
    operator.Align4DCameraToView,
    
    operator.DebugViewportInfo,
    operator.Delete4DCamera,
    operator.EnableStatusFilters,
    operator.DisableStatusFilters,
    operator.ActivateStatusFilters,
    operator.SelectStatusFilter,
    operator.UpdateActiveProfileGroup,
    operator.InitializeProfileSystem,
    operator.BIM_OT_cleanup_profile_groups,
    operator.BIM_OT_init_default_all_tasks,
    operator.VerifyCustomGroupsExclusion,
    operator.ShowProfileUIState,
    operator.AddAppearanceProfile,
    operator.RemoveAppearanceProfile,
    operator.ExportAppearanceProfileSetToFile,
    operator.ImportAppearanceProfileSetFromFile,
    operator.CleanupTaskProfileMappings,

        operator.SetupTextHUD,
    operator.ClearTextHUD,
    operator.UpdateTextHUDPositions,
    operator.UpdateTextHUDScale,
    operator.ToggleTextHUD,
    # Operadores del HUD con GPU (NUEVOS)
    operator.EnableScheduleHUD,
    operator.DisableScheduleHUD,
    operator.ToggleScheduleHUD,
    operator.RefreshScheduleHUD,

    # --- INICIO DEL BLOQUE A AÑADIR ---
    # Operadores del HUD con Compositor (NUEVOS)
    operator.SetupHUDCompositor,
    operator.RemoveHUDCompositor,
    # --- FIN DEL BLOQUE A AÑADIR ---


    # --- Filter Set Operators (Saved/Load/Import/Export) ---
    operator.AddTaskFilter,
    operator.RemoveTaskFilter,
    operator.ApplyTaskFilters,
    operator.FilterDatePicker,
    operator.SaveFilterSet,
    operator.LoadFilterSet,
    operator.RemoveFilterSet,
    operator.UpdateSavedFilterSet,
    operator.ExportFilterSet,
    operator.ImportFilterSet,

# Property groups from prop.py
    prop.WorkPlan,
    prop.BIMWorkPlanProperties,
    prop.TaskProfileGroupChoice,
    prop.Task,
    prop.TaskResource,
    prop.TaskProduct,
    prop.IFCStatus,
    prop.BIMStatusProperties,
    # --- Filter Property Groups ---
    prop.TaskFilterRule,
    prop.BIMTaskFilterProperties,
    prop.SavedFilterSet,

    prop.BIMWorkScheduleProperties,
    prop.BIMTaskTreeProperties,
    prop.BIMTaskTypeColor,
    prop.AppearanceProfile,
    prop.AnimationProfileGroupItem,
    prop.BIMAnimationProperties,
    prop.WorkCalendar,
    prop.RecurrenceComponent,
    prop.BIMWorkCalendarProperties,
    prop.DatePickerProperties,
    prop.BIMDateTextProperties,

    # UI Panels & Lists from ui.py
    ui.BIM_PT_status,
    ui.BIM_PT_work_plans,
    ui.BIM_PT_work_schedules,
    ui.BIM_PT_work_calendars,
    ui.BIM_PT_animation_tools,
    ui.BIM_PT_task_icom,
    ui.BIM_UL_task_columns,
    ui.BIM_UL_task_filters,
    ui.BIM_UL_saved_filter_sets,
    ui.BIM_UL_task_inputs,
    ui.BIM_UL_task_resources,
    ui.BIM_UL_task_outputs,
    ui.BIM_UL_tasks,
    ui.BIM_UL_animation_group_stack,
    ui.BIM_PT_4D_Tools,
    ui.BIM_UL_animation_colors,
    ui.BIM_UL_product_input_tasks,
    ui.BIM_UL_product_output_tasks,
    ui.BIM_PT_appearance_profiles,
)

# --- Optional registration: ClearAnimationAdvanced (guarded) ---
try:
    _ADV = operator.ClearAnimationAdvanced
except Exception:
    _ADV = None
if _ADV:
    try:
        classes = tuple(list(classes) + [_ADV])
    except Exception:
        pass
# --- end optional registration ---



def menu_func_export(self, context):
    self.layout.operator(operator.ExportP6.bl_idname, text="P6 (.xml)")
    self.layout.operator(operator.ExportMSP.bl_idname, text="Microsoft Project (.xml)")


def menu_func_import(self, context):
    self.layout.operator(operator.ImportWorkScheduleCSV.bl_idname, text="Work Schedule (.csv)")
    self.layout.operator(operator.ImportP6.bl_idname, text="P6 (.xml)")
    self.layout.operator(operator.ImportP6XER.bl_idname, text="P6 (.xer)")
    self.layout.operator(operator.ImportPP.bl_idname, text="Powerproject (.pp)")
    self.layout.operator(operator.ImportMSP.bl_idname, text="Microsoft Project (.xml)")


def register():
    # Register all classes for this module
    try:
        for cls in classes:
            try:
                bpy.utils.register_class(cls)
            except Exception:
                pass
    except Exception:
        pass


    # --- NEW: register camera orbit property group and test operators ---
    try:
        bpy.utils.register_class(prop.BIMCameraOrbitProperties)
    except Exception:
        pass
    try:
        bpy.utils.register_class(operator.ResetCameraSettings)
    except Exception:
        pass


    # --- NEW: dynamically attach camera_orbit pointer after classes are registered ---
    try:
        if not hasattr(prop.BIMAnimationProperties, 'camera_orbit'):
            prop.BIMAnimationProperties.camera_orbit = bpy.props.PointerProperty(type=prop.BIMCameraOrbitProperties)
    except Exception as _e:
        print("camera_orbit dynamic attach failed:", _e)
    bpy.types.Scene.show_saved_profiles_section = bpy.props.BoolProperty(name="Show Saved Profiles", default=True)
    bpy.types.Scene.BIMWorkPlanProperties = bpy.props.PointerProperty(type=prop.BIMWorkPlanProperties)
    bpy.types.Scene.BIMWorkScheduleProperties = bpy.props.PointerProperty(type=prop.BIMWorkScheduleProperties)
    bpy.types.Scene.BIMTaskTreeProperties = bpy.props.PointerProperty(type=prop.BIMTaskTreeProperties)
    bpy.types.Scene.BIMWorkCalendarProperties = bpy.props.PointerProperty(type=prop.BIMWorkCalendarProperties)
    bpy.types.Scene.BIMStatusProperties = bpy.props.PointerProperty(type=prop.BIMStatusProperties)
    bpy.types.Scene.BIMAnimationProperties = bpy.props.PointerProperty(type=prop.BIMAnimationProperties)
    bpy.types.Scene.DatePickerProperties = bpy.props.PointerProperty(type=prop.DatePickerProperties)
    bpy.types.TextCurve.BIMDateTextProperties = bpy.props.PointerProperty(type=prop.BIMDateTextProperties)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

# --- Seed DEFAULT Appearance Profile group if none exists, and select it ---
try:
    import json
    scn = bpy.context.scene
    key = "BIM_AppearanceProfileSets"
    raw = scn.get(key, "{}")
    data = {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        data = {}
    if not isinstance(data, dict) or not data:
        default_names = [
            "ATTENDANCE", "CONSTRUCTION", "DEMOLITION", "DISMANTLE",
            "DISPOSAL", "INSTALLATION", "LOGISTIC", "MAINTENANCE",
            "MOVE", "OPERATION", "REMOVAL", "RENOVATION",
        ]
        data = {"DEFAULT": {"profiles": [{"name": n} for n in default_names]}}
        scn[key] = json.dumps(data)
    # try to select DEFAULT in the UI
    try:
        scn.BIMAnimationProperties.profile_groups = "DEFAULT"
    except Exception:
        pass
except Exception:
    pass


def unregister():
    # Unregister classes in reverse order
    try:
        for cls in reversed(classes):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
    except Exception:
        pass

    # --- NEW: remove dynamic camera_orbit pointer ---
    try:
        if hasattr(prop.BIMAnimationProperties, 'camera_orbit'):
            delattr(prop.BIMAnimationProperties, 'camera_orbit')
    except Exception:
        pass
    # --- NEW: unregister test operators and camera orbit PG ---
    try:
        bpy.utils.unregister_class(operator.ResetCameraSettings)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(prop.BIMCameraOrbitProperties)
    except Exception:
        pass

    if hasattr(bpy.types.Scene, 'show_saved_profiles_section'):
        del bpy.types.Scene.show_saved_profiles_section
    if hasattr(bpy.types.Scene, 'BIMWorkPlanProperties'):
        del bpy.types.Scene.BIMWorkPlanProperties
    if hasattr(bpy.types.Scene, 'BIMWorkScheduleProperties'):
        del bpy.types.Scene.BIMWorkScheduleProperties
    if hasattr(bpy.types.Scene, 'BIMTaskTreeProperties'):
        del bpy.types.Scene.BIMTaskTreeProperties
    if hasattr(bpy.types.Scene, 'BIMWorkCalendarProperties'):
        del bpy.types.Scene.BIMWorkCalendarProperties
    if hasattr(bpy.types.Scene, 'BIMStatusProperties'):
        del bpy.types.Scene.BIMStatusProperties
    if hasattr(bpy.types.Scene, 'DatePickerProperties'):
        del bpy.types.Scene.DatePickerProperties
    if hasattr(bpy.types.Scene, 'BIMAnimationProperties'):
        del bpy.types.Scene.BIMAnimationProperties
    if hasattr(bpy.types.TextCurve, 'BIMDateTextProperties'):
        del bpy.types.TextCurve.BIMDateTextProperties
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)