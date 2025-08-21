import bpy
from bpy.types import UIList, Panel

# Toggle para mostrar/ocultar sección de perfiles guardados
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

import bpy
from bpy.types import UIList, Panel
import ifcopenshell
import isodate
import json
import bonsai.tool as tool
import bonsai.bim.helper
from bpy.types import Panel, UIList
from bonsai.bim.helper import draw_attributes
from bonsai.bim.module.sequence.data import (
    WorkPlansData,
    WorkScheduleData,
    SequenceData,
    TaskICOMData,
    AnimationColorSchemeData,
)
from bonsai.bim.module.sequence.prop import UnifiedProfileManager, monitor_predefined_type_change
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bonsai.bim.prop import Attribute
    from bonsai.bim.module.sequence.prop import BIMWorkScheduleProperties, BIMTaskTreeProperties, Task


class BIM_PT_status(Panel):
    bl_label = "Status"
    bl_idname = "BIM_PT_status"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_status"
    bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        return tool.Ifc.get()

    def draw(self, context):

        # Botones de mantenimiento de perfiles

        row = self.layout.row(align=True)

        row.operator('bim.cleanup_profile_groups', icon='TRASH', text='Clean Invalid Profiles')

        row.operator('bim.initialize_profile_system', icon='PLUS', text='Init DEFAULT All Tasks')


        self.props = tool.Sequence.get_status_props()

        assert self.layout
        if not self.props.is_enabled:
            row = self.layout.row()
            row.operator("bim.enable_status_filters", icon="GREASEPENCIL")
            return

        row = self.layout.row(align=True)
        row.label(text="Statuses found in the project:")
        row.operator("bim.activate_status_filters", icon="FILE_REFRESH", text="")
        row.operator("bim.disable_status_filters", icon="CANCEL", text="")

        for status in self.props.statuses:
            row = self.layout.row(align=True)
            row.label(text=status.name)
            row.prop(status, "is_visible", text="", emboss=False, icon="HIDE_OFF" if status.is_visible else "HIDE_ON")
            row.operator("bim.select_status_filter", icon="RESTRICT_SELECT_OFF", text="").name = status.name


class BIM_PT_work_plans(Panel):
    bl_label = "Work Plans"
    bl_idname = "BIM_PT_work_plans"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"

    @classmethod
    def poll(cls, context):
        file = tool.Ifc.get()
        return file and file.schema != "IFC2X3"

    def draw(self, context):
        if not WorkPlansData.is_loaded:
            WorkPlansData.load()
        assert self.layout
        self.props = tool.Sequence.get_work_plan_props()

        row = self.layout.row()
        if WorkPlansData.data["total_work_plans"]:
            row.label(text=f"{WorkPlansData.data['total_work_plans']} Work Plans Found", icon="TEXT")
        else:
            row.label(text="No Work Plans found.", icon="TEXT")
        row.operator("bim.add_work_plan", icon="ADD", text="")
        for work_plan in WorkPlansData.data["work_plans"]:
            self.draw_work_plan_ui(work_plan)

    def draw_work_plan_ui(self, work_plan: dict[str, Any]) -> None:
        row = self.layout.row(align=True)
        row.label(text=work_plan["name"], icon="TEXT")
        if self.props.active_work_plan_id == work_plan["id"]:
            if self.props.editing_type == "ATTRIBUTES":
                row.operator("bim.edit_work_plan", text="", icon="CHECKMARK")
            row.operator("bim.disable_editing_work_plan", text="Cancel", icon="CANCEL")
        elif self.props.active_work_plan_id:
            row.operator("bim.remove_work_plan", text="", icon="X").work_plan = work_plan["id"]
        else:
            op = row.operator("bim.enable_editing_work_plan_schedules", text="", icon="LINENUMBERS_ON")
            op.work_plan = work_plan["id"]
            op = row.operator("bim.enable_editing_work_plan", text="", icon="GREASEPENCIL")
            op.work_plan = work_plan["id"]
            row.operator("bim.remove_work_plan", text="", icon="X").work_plan = work_plan["id"]

        if self.props.active_work_plan_id == work_plan["id"]:
            if self.props.editing_type == "ATTRIBUTES":
                self.draw_editable_ui()
            elif self.props.editing_type == "SCHEDULES":
                self.draw_work_schedule_ui()

    def draw_editable_ui(self) -> None:
        draw_attributes(self.props.work_plan_attributes, self.layout)

    def draw_work_schedule_ui(self) -> None:
        if WorkPlansData.data["has_work_schedules"]:
            row = self.layout.row(align=True)
            row.prop(self.props, "work_schedules", text="")
            op = row.operator("bim.assign_work_schedule", text="", icon="ADD")
            op.work_plan = self.props.active_work_plan_id
            op.work_schedule = int(self.props.work_schedules)
            for work_schedule in WorkPlansData.data["active_work_plan_schedules"]:
                row = self.layout.row(align=True)
                row.label(text=work_schedule["name"], icon="LINENUMBERS_ON")
                op = row.operator("bim.unassign_work_schedule", text="", icon="X")
                op.work_plan = self.props.active_work_plan_id
                op.work_schedule = work_schedule["id"]
        else:
            row = self.layout.row()
            row.label(text="No schedules found. See Work Schedule Panel", icon="INFO")


class BIM_PT_work_schedules(Panel):
    bl_label = "Work Schedules"
    bl_idname = "BIM_PT_work_schedules"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"

    @classmethod
    def poll(cls, context):
        file = tool.Ifc.get()
        return file and hasattr(file, "schema") and file.schema != "IFC2X3"

    def draw(self, context):
        if not SequenceData.is_loaded:
            SequenceData.load()
        if not WorkScheduleData.is_loaded:
            WorkScheduleData.load()
        self.props = tool.Sequence.get_work_schedule_props()
        self.tprops = tool.Sequence.get_task_tree_props()

        if not self.props.active_work_schedule_id:
            row = self.layout.row(align=True)
            if SequenceData.data["has_work_schedules"]:
                row.label(
                    text="{} Work Schedules Found".format(SequenceData.data["number_of_work_schedules_loaded"]),
                    icon="TEXT",
                )
            else:
                row.label(text="No Work Schedules found.", icon="TEXT")
            row.operator("bim.add_work_schedule", text="", icon="ADD")
            row.operator("bim.import_work_schedule_csv", text="", icon="IMPORT")

        for work_schedule_id, work_schedule in SequenceData.data["work_schedules"].items():
            self.draw_work_schedule_ui(work_schedule_id, work_schedule)

    def draw_work_schedule_ui(self, work_schedule_id: int, work_schedule: dict[str, Any]) -> None:
        assert self.layout
        if work_schedule["PredefinedType"] == "BASELINE":
            self.draw_readonly_work_schedule_ui(work_schedule_id)
        else:
            row = self.layout.row(align=True)
            if self.props.active_work_schedule_id == work_schedule_id:
                row.label(
                    text="Currently editing: {}[{}]".format(work_schedule["Name"], work_schedule["PredefinedType"]),
                    icon="LINENUMBERS_ON",
                )
                if self.props.editing_type == "WORK_SCHEDULE":
                    row.operator("bim.edit_work_schedule", text="", icon="CHECKMARK")
                    row.operator("bim.disable_editing_work_schedule", text="", icon="CANCEL")
                elif self.props.editing_type == "TASKS":
                    grid = self.layout.grid_flow(columns=2, even_columns=True)
                    col = grid.column()
                    row1 = col.row(align=True)
                    row1.alignment = "LEFT"
                    row1.label(text="Schedule tools")
                    row1 = col.row(align=True)
                    row1.alignment = "RIGHT"
                    row1.operator("bim.generate_gantt_chart", text="Generate Gantt", icon="NLA").work_schedule = (
                        work_schedule_id
                    )
                    row1.operator(
                        "bim.recalculate_schedule", text="Re-calculate Schedule", icon="FILE_REFRESH"
                    ).work_schedule = work_schedule_id
                    row2 = col.row(align=True)
                    row2.alignment = "RIGHT"
                    row2.operator(
                        "bim.select_work_schedule_products", text="Select Assigned", icon="RESTRICT_SELECT_OFF"
                    ).work_schedule = work_schedule_id
                    row2.operator(
                        "bim.select_unassigned_work_schedule_products",
                        text="Select Unassigned",
                        icon="RESTRICT_SELECT_OFF",
                    ).work_schedule = work_schedule_id
                    if WorkScheduleData.data["can_have_baselines"]:
                        row3 = col.row()
                        row3.alignment = "RIGHT"
                        row3.prop(self.props, "should_show_schedule_baseline_ui", icon="RESTRICT_INSTANCED_OFF")
                    col = grid.column()
                    row1 = col.row(align=True)
                    row1.alignment = "LEFT"
                    row1.label(text="Settings")
                    row1 = col.row(align=True)
                    row1.alignment = "RIGHT"
                    
                    # --- RESTAURAR BOTONES COMO ESTABAN ---
                    row1.prop(self.props, "should_show_column_ui", text="Schedule Columns", toggle=True, icon="SHORTDISPLAY")
                    row1.prop(self.props.filters, "show_filters", text="Filter Columns", toggle=True, icon="FILTER")
                    
                    row2 = col.row(align=True)
                    row.operator("bim.disable_editing_work_schedule", text="Cancel", icon="CANCEL")
            if not self.props.active_work_schedule_id:
                grid = self.layout.grid_flow(columns=2, even_columns=True)
                col1 = grid.column()
                col1.label(
                    text="{}[{}]".format(work_schedule["Name"], work_schedule["PredefinedType"]) or "Unnamed",
                    icon="LINENUMBERS_ON",
                )
                col2 = grid.column()
                row = col2.row(align=True)
                row.alignment = "RIGHT"
                row.operator("bim.enable_editing_work_schedule_tasks", text="", icon="ACTION").work_schedule = (
                    work_schedule_id
                )
                row.operator("bim.enable_editing_work_schedule", text="", icon="GREASEPENCIL").work_schedule = (
                    work_schedule_id
                )
                row.operator("bim.copy_work_schedule", text="", icon="DUPLICATE").work_schedule = work_schedule_id
                row.operator("bim.remove_work_schedule", text="", icon="X").work_schedule = work_schedule_id
            if self.props.active_work_schedule_id == work_schedule_id:
                if self.props.editing_type == "WORK_SCHEDULE":
                    self.draw_editable_work_schedule_ui()
                elif self.props.editing_type == "TASKS":
                    self.draw_baseline_ui(work_schedule_id)
                    self.draw_column_ui()
                    # VOLVER AL SISTEMA ORIGINAL - Solo llamar si está activado
                    if getattr(self.props.filters, "show_filters", False):
                        self.draw_filter_ui()
                    self.draw_editable_task_ui(work_schedule_id)

    def draw_task_operators(self) -> None:
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        ifc_definition_id = None
        if self.tprops.tasks and self.props.active_task_index < len(self.tprops.tasks):
            task = self.tprops.tasks[self.props.active_task_index]
            ifc_definition_id = task.ifc_definition_id
        if ifc_definition_id:
            if self.props.active_task_id:
                if self.props.editing_task_type == "TASKTIME":
                    row.operator("bim.edit_task_time", text="", icon="CHECKMARK")
                elif self.props.editing_task_type == "ATTRIBUTES":
                    row.operator("bim.edit_task", text="", icon="CHECKMARK")
                row.operator("bim.disable_editing_task", text="Cancel", icon="CANCEL")
            elif self.props.editing_task_type == "SEQUENCE":
                row.operator("bim.disable_editing_task", text="Cancel", icon="CANCEL")
            else:
                row.prop(self.props, "show_task_operators", text="Edit", icon="GREASEPENCIL")
                if self.props.show_task_operators:
                    row2 = self.layout.row(align=True)
                    row2.alignment = "RIGHT"

                    row2.prop(self.props, "enable_reorder", text="", icon="SORTALPHA")
                    row2.operator("bim.enable_editing_task_sequence", text="", icon="TRACKING")
                    row2.operator("bim.enable_editing_task_time", text="", icon="TIME").task = ifc_definition_id
                    row2.operator("bim.enable_editing_task_calendar", text="", icon="VIEW_ORTHO").task = (
                        ifc_definition_id
                    )
                    row2.operator("bim.enable_editing_task_attributes", text="", icon="GREASEPENCIL").task = (
                        ifc_definition_id
                    )
                row.operator("bim.add_task", text="Add", icon="ADD").task = ifc_definition_id
                row.operator("bim.duplicate_task", text="Copy", icon="DUPLICATE").task = ifc_definition_id
                row.operator("bim.remove_task", text="Delete", icon="X").task = ifc_definition_id

    def draw_column_ui(self) -> None:
        if not self.props.should_show_column_ui:
            return
        assert self.layout
        row = self.layout.row()
        row.operator("bim.setup_default_task_columns", text="Setup Default Columns", icon="ANCHOR_BOTTOM")
        row.alignment = "RIGHT"
        row = self.layout.row(align=True)
        row.prop(self.props, "column_types", text="")
        column_type = self.props.column_types
        if column_type == "IfcTask":
            row.prop(self.props, "task_columns", text="")
            name, data_type = self.props.task_columns.split("/")
        elif column_type == "IfcTaskTime":
            row.prop(self.props, "task_time_columns", text="")
            name, data_type = self.props.task_time_columns.split("/")
        elif column_type == "Special":
            row.prop(self.props, "other_columns", text="")
            column_type, name = self.props.other_columns.split(".")
            data_type = "string"
        row.operator("bim.set_task_sort_column", text="", icon="SORTALPHA").column = f"{column_type}.{name}"
        row.prop(
            self.props, "is_sort_reversed", text="", icon="SORT_DESC" if self.props.is_sort_reversed else "SORT_ASC"
        )
        op = row.operator("bim.add_task_column", text="", icon="ADD")
        op.column_type = column_type
        op.name = name
        op.data_type = data_type

        # === RESTAURAR EL CANVAS DE COLUMNAS ===
        self.layout.template_list("BIM_UL_task_columns", "", self.props, "columns", self.props, "active_column_index")
    # Reemplaza el método draw_filter_ui existente en ui.py con este

    def draw_filter_ui(self) -> None:
        """Draws the filter configuration panel with the final corrected structure."""
        props = self.props

        if not getattr(props.filters, "show_filters", False):
            return

        main_box = self.layout.box()

        # 1. Título estático "Smart Filter"
        header_row = main_box.row(align=True)
        header_row.label(text="Smart Filter", icon="FILTER")

        # 2. Panel de filtros activos
        active_filters_box = main_box.box()
        row = active_filters_box.row(align=True)
        row.prop(props.filters, "logic", text="")
        row.operator("bim.add_task_filter", text="", icon='ADD')
        row.operator("bim.remove_task_filter", text="", icon='REMOVE')

        # --- INICIO DE CÓDIGO AÑADIDO ---
        row.separator()
        row.operator("bim.apply_task_filters", text="Apply Filters", icon="FILE_REFRESH")
        # --- FIN DE CÓDIGO AÑADIDO ---

        active_filters_box.template_list(
            "BIM_UL_task_filters", "",
            props.filters, "rules",
            props.filters, "active_rule_index"
        )

        active_filters_count = len([r for r in props.filters.rules if r.is_active])
        if active_filters_count > 0:
            info_row = active_filters_box.row()
            info_row.label(text=f"ℹ️ {active_filters_count} active filter(s)", icon='INFO')

        # 3. Panel de Filtros Guardados (ahora colapsable)
        saved_filters_box = main_box.box()
        row = saved_filters_box.row(align=True)

        # --- INICIO DE LA MODIFICACIÓN ---
        # El título ahora es un botón para mostrar/ocultar la sección
        icon = 'TRIA_DOWN' if props.filters.show_saved_filters else 'TRIA_RIGHT'
        row.prop(props.filters, "show_saved_filters", text="Saved Filters", icon=icon, emboss=False)
        # --- FIN DE LA MODIFICACIÓN ---

        # El contenido solo se dibuja si la sección está expandida
        if props.filters.show_saved_filters:
            saved_filters_box.template_list(
                "BIM_UL_saved_filter_sets", "",
                props, "saved_filter_sets",
                props, "active_saved_filter_set_index"
            )

            row_ops = saved_filters_box.row(align=True)
            row_ops.enabled = len(props.saved_filter_sets) > 0

            load_op = row_ops.operator("bim.load_filter_set", text="Load", icon="FILE_TICK")
            load_op.set_index = props.active_saved_filter_set_index

            # --- INICIO DE CÓDIGO AÑADIDO ---
            update_op = row_ops.operator("bim.update_saved_filter_set", text="Update", icon="FILE_REFRESH")
            update_op.set_index = props.active_saved_filter_set_index
            # --- FIN DE CÓDIGO AÑADIDO ---

            remove_op = row_ops.operator("bim.remove_filter_set", text="Remove", icon="TRASH")
            remove_op.set_index = props.active_saved_filter_set_index

            row_io = saved_filters_box.row(align=True)
            row_io.operator("bim.save_filter_set", text="Save Current", icon="PINNED")
            row_io.operator("bim.import_filter_set", text="Import Library", icon="IMPORT")
            row_io.operator("bim.export_filter_set", text="Export Library", icon="EXPORT")




    def draw_editable_work_schedule_ui(self):
        draw_attributes(self.props.work_schedule_attributes, self.layout)

    def draw_editable_task_ui(self, work_schedule_id: int) -> None:
        assert self.layout
        # --- CÓDIGO DUPLICADO ELIMINADO ---
        # La llamada a self.draw_filter_ui() fue removida de aquí
        # ya que se llama correctamente en draw_work_schedule_ui()
        
        row = self.layout.row(align=True)
        row.label(text="Task Tools")
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        # Refresh outputs counts
        row.operator("bim.refresh_task_output_counts", text="", icon="FILE_REFRESH")
        row.operator("bim.add_summary_task", text="Add Summary Task", icon="ADD").work_schedule = work_schedule_id
        row.operator("bim.expand_all_tasks", text="Expand All")
        row.operator("bim.contract_all_tasks", text="Contract All")
        row = self.layout.row(align=True)
        self.draw_task_operators()
        BIM_UL_tasks.draw_header(self.layout)
        self.layout.template_list(
            "BIM_UL_tasks",
            "",
            self.tprops,
            "tasks",
            self.props,
            "active_task_index",
        )

        if self.props.active_task_id and self.props.editing_task_type == "ATTRIBUTES":
            self.draw_editable_task_attributes_ui()
        elif self.props.active_task_id and self.props.editing_task_type == "CALENDAR":
            self.draw_editable_task_calendar_ui()
        elif self.props.highlighted_task_id and self.props.editing_task_type == "SEQUENCE":
            self.draw_editable_task_sequence_ui()
        elif self.props.active_task_time_id and self.props.editing_task_type == "TASKTIME":
            self.draw_editable_task_time_attributes_ui()

    def draw_editable_task_sequence_ui(self):
        task = SequenceData.data["tasks"][self.props.highlighted_task_id]
        row = self.layout.row()
        row.label(text="{} Predecessors".format(len(task["IsSuccessorFrom"])), icon="BACK")
        for sequence_id in task["IsSuccessorFrom"]:
            self.draw_editable_sequence_ui(SequenceData.data["sequences"][sequence_id], "RelatingProcess")

        row = self.layout.row()
        row.label(text="{} Successors".format(len(task["IsPredecessorTo"])), icon="FORWARD")
        for sequence_id in task["IsPredecessorTo"]:
            self.draw_editable_sequence_ui(SequenceData.data["sequences"][sequence_id], "RelatedProcess")

    def draw_editable_sequence_ui(self, sequence, process_type):
        task = SequenceData.data["tasks"][sequence[process_type]]
        row = self.layout.row(align=True)
        row.operator("bim.go_to_task", text="", icon="RESTRICT_SELECT_OFF").task = task["id"]
        row.label(text=task["Identification"] or "XXX")
        row.label(text=task["Name"] or "Unnamed")
        row.label(text=sequence["SequenceType"] or "N/A")
        if sequence["TimeLag"]:
            row.operator("bim.unassign_lag_time", text="", icon="X").sequence = sequence["id"]
            row.label(text=isodate.duration_isoformat(SequenceData.data["lag_times"][sequence["TimeLag"]]["LagValue"]))
        else:
            row.operator("bim.assign_lag_time", text="Add Time Lag", icon="ADD").sequence = sequence["id"]
        if self.props.active_sequence_id == sequence["id"]:
            if self.props.editing_sequence_type == "ATTRIBUTES":
                row.operator("bim.edit_sequence_attributes", text="", icon="CHECKMARK")
                row.operator("bim.disable_editing_sequence", text="Cancel", icon="CANCEL")
                self.draw_editable_sequence_attributes_ui()
            elif self.props.editing_sequence_type == "LAG_TIME":
                op = row.operator("bim.edit_sequence_lag_time", text="", icon="CHECKMARK")
                op.lag_time = sequence["TimeLag"]
                row.operator("bim.disable_editing_sequence", text="Cancel", icon="CANCEL")
                self.draw_editable_sequence_lag_time_ui()
        else:
            if sequence["TimeLag"]:
                op = row.operator("bim.enable_editing_sequence_lag_time", text="Edit Time Lag", icon="CON_LOCKTRACK")
                op.sequence = sequence["id"]
                op.lag_time = sequence["TimeLag"]
            op = row.operator("bim.enable_editing_sequence_attributes", text="Edit Sequence", icon="GREASEPENCIL")
            op.sequence = sequence["id"]
            if process_type == "RelatingProcess":
                op = row.operator("bim.unassign_predecessor", text="", icon="X")
            elif process_type == "RelatedProcess":
                op = row.operator("bim.unassign_successor", text="", icon="X")
            op.task = task["id"]

    def draw_editable_sequence_attributes_ui(self):
        bonsai.bim.helper.draw_attributes(self.props.sequence_attributes, self.layout)

    def draw_editable_sequence_lag_time_ui(self):
        bonsai.bim.helper.draw_attributes(self.props.lag_time_attributes, self.layout)

    def draw_editable_task_calendar_ui(self):
        task = SequenceData.data["tasks"][self.props.active_task_id]
        if task["HasAssignmentsWorkCalendar"]:
            row = self.layout.row(align=True)
            calendar = SequenceData.data["work_calendars"][task["HasAssignmentsWorkCalendar"][0]]
            row.label(text=calendar["Name"] or "Unnamed")
            op = row.operator("bim.remove_task_calendar", text="", icon="X")
            op.work_calendar = task["HasAssignmentsWorkCalendar"][0]
            op.task = self.props.active_task_id
        elif SequenceData.data["has_work_calendars"]:
            row = self.layout.row(align=True)
            row.prop(self.props, "work_calendars", text="")
            op = row.operator("bim.edit_task_calendar", text="", icon="ADD")
            op.work_calendar = int(self.props.work_calendars)
            op.task = self.props.active_task_id
        else:
            row = self.layout.row(align=True)
            row.label(text="Must Create a Calendar First. See Work Calendar Panel", icon="INFO")

    def draw_editable_task_attributes_ui(self):
        # Draw attributes but inject Appearance Profile after 'Priority'
        try:
            attrs = [a for a in self.props.task_attributes if a.name != "PredefinedType"]
        except Exception:
            attrs = list(self.props.task_attributes)

        # Split at Priority
        before = []
        after = []
        found = False
        for a in attrs:
            before.append(a)
            if a.name == "Priority":
                found = True
                break
        if found:
            after = attrs[len(before):]

        import bonsai.bim.helper as _h
        _h.draw_attributes(before, self.layout, copy_operator="bim.copy_task_attribute")


        # --- Draw PredefinedType exactly below Priority (as in Blender 4.2.1) ---
        try:
            _predef = None
            for _a in self.props.task_attributes:
                if getattr(_a, "name", "") == "PredefinedType":
                    _predef = _a
                    break
            if _predef is not None:
                _h.draw_attributes([_predef], self.layout, copy_operator="bim.copy_task_attribute")
        except Exception:
            pass
        # --- end PredefinedType ---

        # Asegura que la tarea activa tenga su grupo DEFAULT sincronizado al dibujarse
        try:
            from bonsai.bim.module.sequence.prop import UnifiedProfileManager

            tprops = tool.Sequence.get_task_tree_props()
            if tprops.tasks and self.props.active_task_index < len(tprops.tasks):
                active_task_pg = tprops.tasks[self.props.active_task_index]
                # Llamada a la lógica central para sincronizar al momento de dibujar
                UnifiedProfileManager.sync_default_group_to_predefinedtype(bpy.context, active_task_pg)
        except Exception as e:
            # No debe romper la UI si algo falla
            print(f"⚠ Error al sincronizar DEFAULT en la UI: {e}")
        # === SECCIÓN CORREGIDA: Custom Appearance Groups ===
        try:
            if self.tprops.tasks and self.props.active_task_index < len(self.tprops.tasks):
                _task = self.tprops.tasks[self.props.active_task_index]
                animation_props = tool.Sequence.get_animation_props()

                # CORRECCIÓN: Usar las funciones implementadas correctamente
                all_groups = UnifiedProfileManager.get_all_groups(bpy.context)
                user_groups = UnifiedProfileManager.get_user_created_groups(bpy.context)

                # Mostrar información de tareas seleccionadas
                selected_count = len([task for task in self.tprops.tasks if getattr(task, 'is_selected', False)])

                # Siempre mostrar la sección si hay grupos disponibles
                if all_groups:
                    box = self.layout.box()

                    # Header con información
                    header_row = box.row(align=True)
                    header_row.label(text="Profile Group Assignment:", icon="GROUP")

                    # Información de tareas seleccionadas
                    if selected_count > 0:
                        info_row = box.row()
                        info_row.label(text=f"📋 {selected_count} tasks selected for copying", icon='INFO')

                        # Botón de copiar
                        copy_row = box.row(align=True)
                        copy_op = copy_row.operator("bim.copy_task_custom_profile_group", text="Copy Configuration to Selected", icon="COPYDOWN")
                        copy_op.enabled = selected_count > 0

                    # Selector de grupo personalizado (solo grupos custom)
                    if user_groups:
                        row = box.row(align=True)
                        row.label(text="Custom Group:")
                        row.prop(animation_props, "task_profile_group_selector", text="")

                        # Mostrar selector de perfil si hay grupo seleccionado
                        current_group = getattr(animation_props, 'task_profile_group_selector', '')
                        if current_group and current_group != "DEFAULT":
                            row = box.row(align=True)
                            row.label(text="Profile:")
                            row.prop(_task, "selected_profile_in_active_group", text="")

                            # Toggle para habilitar/deshabilitar
                            if getattr(_task, "selected_profile_in_active_group", ""):
                                row = box.row(align=True)
                                row.prop(_task, "use_active_profile_group", text="Enable custom assignment")
                        else:
                            # Mostrar mensaje cuando no hay grupo seleccionado
                            info_row = box.row()
                            info_row.label(text="ℹ️ Select a custom group to assign profiles", icon='INFO')
                    else:
                        # Mensaje cuando no hay grupos personalizados
                        info_row = box.row()
                        info_row.label(text="ℹ️ No custom groups available. Create one in Appearance Profiles.", icon='INFO')

                # Sección colapsible de perfiles guardados (simplificada)
                row_saved = self.layout.row(align=True)
                icon = 'TRIA_DOWN' if self.props.show_saved_profiles_section else 'TRIA_RIGHT'
                row_saved.prop(self.props, "show_saved_profiles_section", text="Profile Assignments Summary", icon=icon, emboss=False)

                if self.props.show_saved_profiles_section:
                    sumbox = self.layout.box()

                    # Mostrar asignaciones de la tarea actual
                    if hasattr(_task, "profile_group_choices") and _task.profile_group_choices:
                        # Ordenar: DEFAULT primero, luego alfabéticamente
                        sorted_choices = sorted(_task.profile_group_choices,
                                              key=lambda x: (x.group_name != "DEFAULT", x.group_name))

                        for choice in sorted_choices:
                            row = sumbox.row(align=True)

                            # Icono diferente para DEFAULT vs custom
                            icon = 'PINNED' if choice.group_name == "DEFAULT" else 'DOT'
                            if choice.enabled:
                                icon = 'RADIOBUT_ON' if choice.group_name != "DEFAULT" else 'PINNED'

                            # Mostrar información
                            profile_name = choice.selected_profile or "(no profile)"
                            status = "✓" if choice.enabled else "○"

                            row.label(text=f"{status} {choice.group_name} → {profile_name}", icon=icon)
                    else:
                        # Inicializar si no hay datos
                        info_row = sumbox.row()
                        info_row.label(text="No profile assignments found", icon='INFO')
                        init_button = sumbox.row()
                        init_button.operator('bim.initialize_profile_system', text="Initialize Profile Assignments", icon='PLUS')

        except Exception as e:
            # Fallback si algo falla
            error_box = self.layout.box()
            error_box.label(text=f"Profile system error: {str(e)}", icon='ERROR')
            error_box.operator('bim.initialize_profile_system', text="Repair Profile System", icon='TOOL_SETTINGS')
    
    def draw_editable_task_time_attributes_ui(self):
        bonsai.bim.helper.draw_attributes(self.props.task_time_attributes, self.layout)

    def draw_baseline_ui(self, work_schedule_id):
        if not self.props.should_show_schedule_baseline_ui:
            return
        row3 = self.layout.row()
        row3.alignment = "RIGHT"
        row3.operator("bim.create_baseline", text="Add Baseline", icon="ADD").work_schedule = work_schedule_id
        if WorkScheduleData.data["active_work_schedule_baselines"]:
            for baseline in WorkScheduleData.data["active_work_schedule_baselines"]:
                baseline_row = self.layout.row()
                baseline_row.alignment = "RIGHT"
                baseline_row.label(
                    text="{} @ {}".format(baseline["name"], baseline["date"]), icon="RESTRICT_INSTANCED_OFF"
                )
                baseline_row.operator("bim.generate_gantt_chart", text="Compare", icon="NLA").work_schedule = baseline[
                    "id"
                ]
                baseline_row.operator(
                    "bim.enable_editing_work_schedule_tasks", text="Display Schedule", icon="ACTION"
                ).work_schedule = baseline["id"]
                baseline_row.operator("bim.remove_work_schedule", text="", icon="X").work_schedule = baseline["id"]

    def draw_readonly_work_schedule_ui(self, work_schedule_id):
        if self.props.active_work_schedule_id == work_schedule_id:
            row = self.layout.row()
            row.alignment = "RIGHT"
            row.operator("bim.disable_editing_work_schedule", text="Disable editing", icon="CANCEL")
            grid = self.layout.grid_flow(columns=2, even_columns=True)
            col = grid.column()
            row1 = col.row(align=True)
            row1.alignment = "LEFT"
            row1.label(text="Settings")
            row1 = col.row(align=True)
            row1.alignment = "RIGHT"
            row1.prop(self.props, "should_show_column_ui", text="Schedule Columns", icon="SHORTDISPLAY")
            row2 = col.row(align=True)
            if self.props.editing_type == "TASKS":
                self.draw_column_ui()
                # ELIMINADO: self.draw_filter_ui() - esto puede estar causando el problema
                self.layout.template_list(
                    "BIM_UL_tasks",
                    "",
                    self.tprops,
                    "tasks",
                    self.props,
                    "active_task_index",
                )



class BIM_UL_animation_group_stack(UIList):
    bl_idname = "BIM_UL_animation_group_stack"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.group)

    def invoke(self, context, event):
        pass


class BIM_PT_animation_tools(Panel):
    bl_label = "Animation Tools"
    bl_idname = "BIM_PT_animation_tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return True

    def draw_processing_options(self):
        layout = self.layout
        self.animation_props = tool.Sequence.get_animation_props()
        camera_props = self.animation_props.camera_orbit

        box = layout.box()
        col = box.column(align=True)

        row = col.row(align=True)
        icon = 'TRIA_DOWN' if camera_props.show_camera_orbit_settings else 'TRIA_RIGHT'
        row.prop(camera_props, "show_camera_orbit_settings", icon=icon, emboss=False, text="Camera & Orbit Settings")

        if camera_props.show_camera_orbit_settings:
            self.draw_camera_orbit_ui()

    def draw_hud_settings_section(self, layout):
        """Dibuja la sección completa del HUD como panel independiente"""
        try:
            camera_props = self.animation_props.camera_orbit
            hud_box = layout.box()
            
            # Header principal del HUD
            hud_header = hud_box.row()
            hud_header.label(text="Viewport HUD", icon="VIEW_CAMERA")
            hud_header.prop(camera_props, "enable_text_hud", text="")
            hud_header.operator("bim.refresh_schedule_hud", text="", icon='FILE_REFRESH')
            
            # Configuraciones completas del HUD
            if getattr(camera_props, "enable_text_hud", False):
                self.draw_camera_hud_settings(hud_box)

        except Exception as e:
            # Fallback si hay problemas
            error_box = layout.box()
            error_box.label(text="Viewport HUD", icon="VIEW_CAMERA")
            error_box.label(text=f"Error: {str(e)}", icon='ERROR')

    def draw_visualisation_ui(self):
        # Appearance Groups (Animation): priority-ordered, selectable & re-orderable
        box = self.layout.box()
        col = box.column(align=True)
        col.label(text="Animation Groups (For Animation/Snapshot):")
        row = col.row()
        row.template_list("BIM_UL_animation_group_stack", "", self.animation_props, "animation_group_stack", self.animation_props, "animation_group_stack_index", rows=3)
        col2 = row.column(align=True)
        # Always enabled: Add
        col2.operator("bim.anim_group_stack_add", text="", icon="ADD")
        # Compute current selection and total for enabling logic
        idx = self.animation_props.animation_group_stack_index
        total = len(self.animation_props.animation_group_stack)
        # Remove: enabled only when a valid item is selected
        _row = col2.row(align=True)
        _row.enabled = (0 <= idx < total)
        _row.operator("bim.anim_group_stack_remove", text="", icon="REMOVE")
        col2.separator()
        # Move Up: enabled only when not the first item
        _row = col2.row(align=True)
        _row.enabled = (idx > 0)
        op = _row.operator("bim.anim_group_stack_move", text="", icon="TRIA_UP")
        op.direction = "UP"
        # Move Down: enabled only when not the last item
        _row = col2.row(align=True)
        _row.enabled = (0 <= idx < total - 1)
        op = _row.operator("bim.anim_group_stack_move", text="", icon="TRIA_DOWN")
        op.direction = "DOWN"

        if not AnimationColorSchemeData.is_loaded:
            AnimationColorSchemeData.load()

        row = self.layout.row(align=True)
        row.label(text="Start Date/ Date Range:", icon="CAMERA_DATA")

        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        def _label_from_iso(val, placeholder):
            try:
                if not val or val.strip() in ("", "-"):
                    return placeholder
                return val.split("T")[0]
            except Exception:
                return placeholder
        op = row.operator("bim.datepicker", text=_label_from_iso(self.props.visualisation_start, "Start Date"), icon="REW")
        op.target_prop = "BIMWorkScheduleProperties.visualisation_start"
        op = row.operator("bim.datepicker", text=_label_from_iso(self.props.visualisation_finish, "Finish Date"), icon="FF")
        op.target_prop = "BIMWorkScheduleProperties.visualisation_finish"
        op = row.operator("bim.guess_date_range", text="Guess", icon="FILE_REFRESH")
        op.work_schedule = self.props.active_work_schedule_id

        row = self.layout.row(align=True)
        row.label(text="Speed Settings")
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        row.prop(self.props, "speed_types", text="")
        if self.props.speed_types == "FRAME_SPEED":
            row.prop(self.props, "speed_animation_frames", text="")
            row.prop(self.props, "speed_real_duration", text="")
        elif self.props.speed_types == "DURATION_SPEED":
            row.prop(self.props, "speed_animation_duration", text="")
            row.label(text="->")
            row.prop(self.props, "speed_real_duration", text="")
        elif self.props.speed_types == "MULTIPLIER_SPEED":
            row.prop(self.props, "speed_multiplier", text="")
        row = self.layout.row(align=True)
        row.label(text="Display Settings")
        row = self.layout.row()
        row.alignment = "RIGHT"
        row = self.layout.row()
        row.alignment = "RIGHT"
        row.prop(self.animation_props, "should_show_task_bar_options", text="Task Bars", icon="NLA_PUSHDOWN")

        if self.animation_props.should_show_task_bar_options:
            box = self.layout.box()
            row = box.row()
            row.label(text="Task Bar Options", icon="NLA_PUSHDOWN")

            # NUEVO: Mostrar información del cronograma para Task Bars
            try:
                schedule_start, schedule_finish = tool.Sequence.get_schedule_date_range()
                if schedule_start and schedule_finish:
                    info_row = box.row()
                    info_row.label(text=f"📅 Schedule: {schedule_start.strftime('%Y-%m-%d')} to {schedule_finish.strftime('%Y-%m-%d')}", icon='TIME')
                    info_row = box.row()
                    info_row.label(text="ℹ️ Task bars align with schedule dates (independent of animation settings)", icon='INFO')
                else:
                    info_row = box.row()
                    info_row.label(text="⚠️ No schedule dates available", icon='ERROR')
            except Exception:
                pass


            # Habilitar selección de tareas
            row = box.row(align=True)
            row.prop(self.props, "should_show_task_bar_selection", text="Enable Selection", icon="CHECKBOX_HLT")

            # Mostrar contador de tareas seleccionadas
            task_count = len(tool.Sequence.get_task_bar_list())
            if task_count > 0:
                row.label(text=f"({task_count} selected)")

            # Botón para generar barras
            row = box.row(align=True)
            row.operator("bim.add_task_bars", text="Generate Bars", icon="VIEW3D")

            # Si hay tareas seleccionadas, mostrar opción para limpiar
            if task_count > 0:
                row.operator("bim.clear_task_bars", text="Clear", icon="TRASH")

            # Colores de las barras
            grid = box.grid_flow(columns=2, even_columns=True)
            col = grid.column()
            row = col.row(align=True)
            row.prop(self.animation_props, "color_progress")

            col = grid.column()
            row = col.row(align=True)
            row.prop(self.animation_props, "color_full")

        self.layout.separator()  # Separador visual

        row = self.layout.row(align=True)
        row.alignment = "RIGHT"

        # Selector de esquema de colores (opcional, ya no se usa)
        if AnimationColorSchemeData.data.get("saved_color_schemes"):
            row.prop(
                self.animation_props,
                "saved_color_schemes",
                text="Color Scheme",
                icon=tool.Blender.SEQUENCE_COLOR_SCHEME_ICON,
            )

        
        # Selector de esquema de colores (opcional, ya no se usa)
        if AnimationColorSchemeData.data.get("saved_color_schemes"):
            row.prop(
                self.animation_props,
                "saved_color_schemes",
                text="Color Scheme",
                icon=tool.Blender.SEQUENCE_COLOR_SCHEME_ICON,
            )

        # === BOTONES PRINCIPALES - Animation Settings ===
        main_actions_box = self.layout.box()
        main_actions_box.label(text="Animation Actions:", icon="OUTLINER_OB_CAMERA")

        # Botón principal
        main_row = main_actions_box.row()
        op = main_row.operator(
            "bim.visualise_work_schedule_date_range",
            text="Create / Update Animation",
            icon="OUTLINER_OB_CAMERA")
        op.work_schedule = self.props.active_work_schedule_id

        # Botón Reset - DUPLICADO
        reset_row = main_actions_box.row()
        reset_row.operator("bim.clear_previous_animation", text="Reset", icon="TRASH")

        # --- Processing Tools (moved below main actions) ---
        self.draw_processing_options()
        
        # === NUEVO: HUD Settings independiente ===
        self.layout.separator()
        self.draw_hud_settings_section(self.layout)

    def draw_snapshot_ui(self):
        # Asegurar propiedades de animación siempre disponibles
        try:
            import bonsai.tool as tool
            self.animation_props = tool.Sequence.get_animation_props()
        except Exception:
            pass  # Si falla, mantenemos el valor previo si existe

        # Etiqueta y selector de fecha
        row = self.layout.row(align=True)
        row.label(text="Date of Snapshot:", icon="CAMERA_STEREO")

        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        def _label_from_iso(val, placeholder):
            try:
                if not val or val.strip() in ("", "-"):
                    return placeholder
                return val.split("T")[0]
            except Exception:
                return placeholder
        op = row.operator("bim.datepicker", text=_label_from_iso(self.props.visualisation_start, "Date"), icon="PROP_PROJECTED")
        op.target_prop = "BIMWorkScheduleProperties.visualisation_start"

        # Caja de información de Grupos de Perfiles Activos
        box = self.layout.box()
        col = box.column(align=True)
        col.label(text="Active Profile Groups:")

        active_groups = []
        try:
            for stack_item in getattr(self.animation_props, "animation_group_stack", []):
                if getattr(stack_item, "enabled", False) and getattr(stack_item, "group", None):
                    active_groups.append(stack_item.group)
        except Exception:
            active_groups = []

        if active_groups:
            for group in active_groups[:3]:
                row = col.row()
                row.label(text=f"  • {group}", icon='DOT')
            if len(active_groups) > 3:
                row = col.row()
                row.label(text=f"  ... and {len(active_groups)-3} more", icon='DOTS_HORIZONTAL')
        else:
            row = col.row()
            row.label(text="  No groups selected (will use DEFAULT)", icon='INFO')

        # === SNAPSHOT ACTIONS (moved above camera controls) ===
        actions_box = self.layout.box()
        actions_box.label(text="Snapshot Actions:", icon="RENDER_STILL")

        # Botón principal para crear el snapshot
        main_row = actions_box.row()
        op = main_row.operator("bim.snapshot_with_profiles_fixed", text="Create SnapShot", icon="CAMERA_STEREO")
        try:
            op.work_schedule = self.props.active_work_schedule_id
        except Exception:
            pass

        # Botón Reset (replicando la posición de Animation Settings)
        reset_row = actions_box.row()
        reset_row.operator("bim.clear_previous_animation", text="Reset", icon="TRASH")

        self.layout.separator()

        # === Snapshot Camera Controls (now below actions) ===
        try:
            import bpy  # Garantizar import local en caso de contextos parciales de Blender
            camera_box = self.layout.box()
            camera_header = camera_box.row()
            camera_header.label(text="Snapshot Camera Controls:", icon="CAMERA_DATA")
            camera_row = camera_box.row(align=True)
            camera_row.operator("bim.add_snapshot_camera", text="Add Camera", icon="OUTLINER_OB_CAMERA")
            camera_row.operator("bim.align_snapshot_camera_to_view", text="Align to View", icon="CAMERA_DATA")

            active_cam = bpy.context.scene.camera if bpy.context and bpy.context.scene else None
            info_row = camera_box.row()
            if active_cam:
                info_row.label(text=f"Active: {active_cam.name}", icon="CAMERA_DATA")
            else:
                info_row.label(text="No active camera", icon="ERROR")
        except Exception:
            pass

        # === NUEVO: HUD Settings para Snapshot ===
        self.layout.separator()
        self.draw_hud_settings_section(self.layout)

    def draw_camera_orbit_ui(self):
        self.animation_props = tool.Sequence.get_animation_props()
        camera_props = self.animation_props.camera_orbit

        # Bloque de Cámara
        box = self.layout.box()
        col = box.column(align=True)
        col.label(text="Camera", icon="CAMERA_DATA")
        row = col.row(align=True)
        row.prop(camera_props, "camera_focal_mm")
        row = col.row(align=True)
        row.prop(camera_props, "camera_clip_start")
        row.prop(camera_props, "camera_clip_end")

        # Bloque de Órbita
        box = self.layout.box()
        col = box.column(align=True)
        col.label(text="Orbit", icon="ORIENTATION_GIMBAL")
        row = col.row(align=True)
        row.prop(camera_props, "orbit_mode", expand=True)

        # Opciones de Radio, Altura, Ángulo y Dirección
        row = col.row(align=True)
        row.prop(camera_props, "orbit_radius_mode", text="")
        sub = row.row(align=True)
        sub.enabled = camera_props.orbit_radius_mode == "MANUAL"
        sub.prop(camera_props, "orbit_radius", text="")
        row = col.row(align=True)
        row.prop(camera_props, "orbit_height")
        row = col.row(align=True)
        row.prop(camera_props, "orbit_start_angle_deg")
        row.prop(camera_props, "orbit_direction", expand=True)

        # Look At
        col.separator()
        row = col.row(align=True)
        row.prop(camera_props, "look_at_mode", expand=True)
        if camera_props.look_at_mode == "OBJECT":
            col.prop(camera_props, "look_at_object")
        
        # Sección de Método y Trayectoria
        col.separator()
        col.label(text="Animation Method & Path:")
        
        row = col.row(align=True)
        row.prop(camera_props, "orbit_path_shape", expand=True)
        
        if camera_props.orbit_path_shape == 'CUSTOM':
            col.prop(camera_props, "custom_orbit_path")

        row = col.row(align=True)
        row.enabled = camera_props.orbit_path_shape == 'CIRCLE'
        row.prop(camera_props, "orbit_path_method", expand=True)

        col.prop(camera_props, "interpolation_mode")
        
        if camera_props.interpolation_mode == 'BEZIER':
            row = col.row(align=True)
            row.prop(camera_props, "bezier_smoothness_factor")
        
        col.prop(camera_props, "hide_orbit_path")
        
        # Opciones de Duración
        col.separator()
        row = col.row(align=True)
        row.prop(camera_props, "orbit_use_4d_duration")
        sub = row.row(align=True)
        sub.enabled = not camera_props.orbit_use_4d_duration
        sub.prop(camera_props, "orbit_duration_frames", text="")

        # Botones de Acción
        col.separator()
        action_row = col.row(align=True)
        action_row.operator("bim.align_4d_camera_to_view", text="Align Cam to View", icon="CAMERA_DATA")
        action_row.operator("bim.reset_camera_settings", text="Reset Settings", icon="FILE_REFRESH")

        # Botón de eliminación
        delete_row = col.row(align=True)
        delete_row.operator("bim.delete_4d_camera", text="Delete 4D Camera", icon="TRASH")

    def draw_camera_hud_settings(self, layout):
        """🖱️ INTERFAZ HUD COMPLETA - Todas las opciones avanzadas"""
        camera_props = self.animation_props.camera_orbit
        
        # NO crear nuevo box aquí, usar el layout recibido
        hud_settings = layout.column()

        # ==========================================
        # === LAYOUT - SECCIÓN COMPLETA ===
        # ==========================================
        layout_box = hud_settings.box()
        layout_box.label(text="Layout", icon="SNAP_GRID")
        
        # Posición
        row = layout_box.row()
        row.prop(camera_props, "hud_position", text="Position")
        
        # Alineación de texto (si existe)
        if hasattr(camera_props, 'hud_text_alignment'):
            row = layout_box.row()
            row.prop(camera_props, "hud_text_alignment", expand=True)

        # Márgenes
        margin_row = layout_box.row(align=True)
        margin_row.prop(camera_props, "hud_margin_horizontal", text="H-Margin")
        margin_row.prop(camera_props, "hud_margin_vertical", text="V-Margin")

        # Escala y Espaciado de líneas
        spacing_row = layout_box.row(align=True)
        spacing_row.prop(camera_props, "hud_scale_factor", text="Scale")
        if hasattr(camera_props, 'hud_text_spacing'):
            spacing_row.prop(camera_props, "hud_text_spacing", text="Line Spacing")

        # Padding
        if hasattr(camera_props, 'hud_padding_horizontal'):
            padding_row = layout_box.row(align=True)
            padding_row.prop(camera_props, "hud_padding_horizontal", text="H-Padding")
            padding_row.prop(camera_props, "hud_padding_vertical", text="V-Padding")

        # ==========================================
        # === COLORS - SECCIÓN COMPLETA ===
        # ==========================================
        colors_box = hud_settings.box()
        colors_box.label(text="Colors", icon="COLOR")
        
        # Colores básicos
        if hasattr(camera_props, 'hud_text_color'):
            colors_box.prop(camera_props, "hud_text_color", text="Text")
        if hasattr(camera_props, 'hud_background_color'):
            colors_box.prop(camera_props, "hud_background_color", text="Background")

        # Gradiente
        if hasattr(camera_props, 'hud_background_gradient_enabled'):
            gradient_row = colors_box.row()
            gradient_row.prop(camera_props, "hud_background_gradient_enabled", text="Gradient")
            
            if getattr(camera_props, "hud_background_gradient_enabled", False):
                colors_box.prop(camera_props, "hud_background_gradient_color", text="Gradient Color")
                if hasattr(camera_props, 'hud_gradient_direction'):
                    colors_box.prop(camera_props, "hud_gradient_direction", text="Direction")

        # ==========================================
        # === BORDERS & EFFECTS - SECCIÓN COMPLETA ===
        # ==========================================
        effects_box = hud_settings.box()
        effects_box.label(text="Borders & Effects", icon="MESH_PLANE")
        
        # Bordes
        if hasattr(camera_props, 'hud_border_width'):
            border_row = effects_box.row(align=True)
            border_row.prop(camera_props, "hud_border_width", text="Border Width")
            if getattr(camera_props, "hud_border_width", 0) > 0 and hasattr(camera_props, 'hud_border_color'):
                border_row.prop(camera_props, "hud_border_color", text="")
        
        if hasattr(camera_props, 'hud_border_radius'):
            effects_box.prop(camera_props, "hud_border_radius", text="Border Radius")

        # ==========================================
        # === SHADOWS - SECCIÓN COMPLETA ===
        # ==========================================
        shadows_box = hud_settings.box()
        shadows_box.label(text="Shadows", icon="LIGHT_SUN")
        
        # Sombra del texto
        if hasattr(camera_props, 'hud_text_shadow_enabled'):
            text_shadow_row = shadows_box.row()
            text_shadow_row.prop(camera_props, "hud_text_shadow_enabled", text="Text Shadow")
            
            if getattr(camera_props, "hud_text_shadow_enabled", False):
                shadow_offset_row = shadows_box.row(align=True)
                if hasattr(camera_props, 'hud_text_shadow_offset_x'):
                    shadow_offset_row.prop(camera_props, "hud_text_shadow_offset_x", text="X")
                if hasattr(camera_props, 'hud_text_shadow_offset_y'):
                    shadow_offset_row.prop(camera_props, "hud_text_shadow_offset_y", text="Y")
                if hasattr(camera_props, 'hud_text_shadow_color'):
                    shadows_box.prop(camera_props, "hud_text_shadow_color", text="Shadow Color")

        # Sombra del fondo
        if hasattr(camera_props, 'hud_background_shadow_enabled'):
            bg_shadow_row = shadows_box.row()
            bg_shadow_row.prop(camera_props, "hud_background_shadow_enabled", text="Background Shadow")
            
            if getattr(camera_props, "hud_background_shadow_enabled", False):
                if hasattr(camera_props, 'hud_background_shadow_offset_x'):
                    bg_shadow_offset_row = shadows_box.row(align=True)
                    bg_shadow_offset_row.prop(camera_props, "hud_background_shadow_offset_x", text="X")
                    bg_shadow_offset_row.prop(camera_props, "hud_background_shadow_offset_y", text="Y")
                if hasattr(camera_props, 'hud_background_shadow_blur'):
                    shadows_box.prop(camera_props, "hud_background_shadow_blur", text="Blur")
                if hasattr(camera_props, 'hud_background_shadow_color'):
                    shadows_box.prop(camera_props, "hud_background_shadow_color", text="Shadow Color")

        # ==========================================
        # === TYPOGRAPHY - SECCIÓN COMPLETA ===
        # ==========================================
        if hasattr(camera_props, 'hud_font_weight'):
            typo_box = hud_settings.box()
            typo_box.label(text="Typography", icon="FONT_DATA")
            
            typo_box.prop(camera_props, "hud_font_weight", text="Weight")
            if hasattr(camera_props, 'hud_letter_spacing'):
                typo_box.prop(camera_props, "hud_letter_spacing", text="Letter Spacing")

    def draw(self, context):
        self.props = tool.Sequence.get_work_schedule_props()
        self.animation_props = tool.Sequence.get_animation_props()
        
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        row.prop(self.props, "should_show_visualisation_ui", text="Animation Settings", icon="SETTINGS")
        row.prop(self.props, "should_show_snapshot_ui", text="Snapshot Settings", icon="SETTINGS")

        if not (self.props.should_show_visualisation_ui or self.props.should_show_snapshot_ui):
            self.props.should_show_visualisation_ui = True

        if self.props.should_show_visualisation_ui:
            self.draw_visualisation_ui()
            self.draw_scene_display_options()
        if self.props.should_show_snapshot_ui:
            self.draw_snapshot_ui()

    def draw_scene_display_options(self):
        """Dibuja las opciones de visualización de la escena"""
        try:
            camera_props = self.animation_props.camera_orbit
            box = self.layout.box()
            col = box.column(align=True)
            col.label(text="Scene Display Options", icon="SCENE_DATA")
            row = col.row()
            row.prop(camera_props, "show_3d_schedule_texts", text="Show 3D Schedule Texts (Legacy)")
        except Exception as e:
            # Dibuja un mensaje de error si las propiedades no están disponibles
            self.layout.label(text=f"Error: {e}", icon='ERROR')


class BIM_PT_task_icom(Panel):
    bl_label = "Task ICOM"
    bl_idname = "BIM_PT_task_icom"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_work_schedules"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        props = tool.Sequence.get_work_schedule_props()
        if not props.active_work_schedule_id:
            return False
        tprops = tool.Sequence.get_task_tree_props()
        total_tasks = len(tprops.tasks)
        if total_tasks > 0 and props.active_task_index < total_tasks:
            return True
        return False

    def draw(self, context):
        if not TaskICOMData.is_loaded:
            TaskICOMData.load()

        self.props = tool.Sequence.get_work_schedule_props()
        self.tprops = tool.Sequence.get_task_tree_props()
        task = self.tprops.tasks[self.props.active_task_index]

        grid = self.layout.grid_flow(columns=3, even_columns=True)

        # Column1
        col = grid.column()

        row2 = col.row(align=True)
        total_task_inputs = len(self.props.task_inputs)
        row2.label(text="Inputs ({})".format(total_task_inputs))

        if context.selected_objects:
            op = row2.operator("bim.assign_process", icon="ADD", text="")
            op.task = task.ifc_definition_id
            op.related_object_type = "PRODUCT"
        if total_task_inputs:
            op = row2.operator("bim.unassign_process", icon="REMOVE", text="")
            op.task = task.ifc_definition_id
            op.related_object_type = "PRODUCT"
            if not context.selected_objects and self.props.active_task_input_index < total_task_inputs:
                input_id = self.props.task_inputs[self.props.active_task_input_index].ifc_definition_id
                op.related_object = input_id

        op = row2.operator("bim.select_task_related_inputs", icon="RESTRICT_SELECT_OFF", text="Select")
        op.task = task.ifc_definition_id

        row2 = col.row()
        row2.prop(self.props, "show_nested_inputs", text="Show Nested")
        row2 = col.row()
        row2.template_list("BIM_UL_task_inputs", "", self.props, "task_inputs", self.props, "active_task_input_index")

        # Column2
        col = grid.column()

        row2 = col.row(align=True)
        total_task_resources = len(self.props.task_resources)
        row2.label(text="Resources ({})".format(total_task_resources))
        op = row2.operator("bim.calculate_task_duration", text="", icon="TEMP")
        op.task = task.ifc_definition_id

        if TaskICOMData.data["can_active_resource_be_assigned"]:
            op = row2.operator("bim.assign_process", icon="ADD", text="")
            op.task = task.ifc_definition_id
            op.related_object_type = "RESOURCE"

        if total_task_resources and self.props.active_task_resource_index < total_task_resources:
            op = row2.operator("bim.unassign_process", icon="REMOVE", text="")
            op.task = task.ifc_definition_id
            op.related_object_type = "RESOURCE"
            op.resource = self.props.task_resources[self.props.active_task_resource_index].ifc_definition_id

        row2 = col.row()
        row2.prop(self.props, "show_nested_resources", text="Show Nested")

        row2 = col.row()
        row2.template_list(
            "BIM_UL_task_resources", "", self.props, "task_resources", self.props, "active_task_resource_index"
        )

        # Column3
        col = grid.column()

        row2 = col.row(align=True)
        total_task_outputs = len(self.props.task_outputs)
        row2.label(text="Outputs ({})".format(total_task_outputs))

        if context.selected_objects:
            op = row2.operator("bim.assign_product", icon="ADD", text="")
            op.task = task.ifc_definition_id
        if total_task_outputs:
            op = row2.operator("bim.unassign_product", icon="REMOVE", text="")
            op.task = task.ifc_definition_id
            if (
                total_task_outputs
                and not context.selected_objects
                and self.props.active_task_output_index < total_task_outputs
            ):
                output_id = self.props.task_outputs[self.props.active_task_output_index].ifc_definition_id
                op.relating_product = output_id

        op = row2.operator("bim.select_task_related_products", icon="RESTRICT_SELECT_OFF", text="Select")
        op.task = task.ifc_definition_id
        row2 = col.row()
        row2.prop(self.props, "show_nested_outputs", text="Show Nested")
        row2 = col.row()
        row2.template_list(
            "BIM_UL_task_outputs", "", self.props, "task_outputs", self.props, "active_task_output_index"
        )


class BIM_UL_task_columns(UIList):
    def draw_item(
        self,
        context,
        layout: bpy.types.UILayout,
        data: "BIMWorkScheduleProperties",
        item: "Attribute",
        icon,
        active_data,
        active_propname,
    ):
        props = tool.Sequence.get_work_schedule_props()
        if item:
            row = layout.row(align=True)
            row.prop(item, "name", emboss=False, text="")
            if props.sort_column == item.name:
                row.label(text="", icon="SORTALPHA")
            row.operator("bim.remove_task_column", text="", icon="X").name = item.name


# === INICIO DE CÓDIGO AÑADIDO PARA FILTROS ===



class BIM_UL_task_filters(UIList):
    """Dibuja la lista de reglas de filtro."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        # 'item' es una instancia de TaskFilterRule
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            # El tipo de dato ahora se lee directamente de la propiedad de la regla
            data_type = getattr(item, 'data_type', 'string')

            row = layout.row(align=True)

            # Controles comunes (checkbox, columna, operador)
            row.prop(item, "is_active", text="")
            row.prop(item, "column", text="")
            row.prop(item, "operator", text="")

            # El campo de valor solo se habilita si el operador lo requiere
            value_row = row.row(align=True)
            value_row.enabled = item.operator not in {'EMPTY', 'NOT_EMPTY'}

            # Lógica condicional para dibujar el widget de valor correcto
            if data_type == 'integer':
                value_row.prop(item, "value_integer", text="")
            elif data_type in ('float', 'real'):
                value_row.prop(item, "value_float", text="")
            elif data_type == 'boolean':
                value_row.prop(item, "value_boolean", text="")
            elif data_type == 'date':
                # Para fechas, mostramos el texto y un botón que abre el calendario
                value_row.prop(item, "value_string", text="")
                # ✅ BOTÓN DEL CALENDARIO CORREGIDO
                op = value_row.operator("bim.filter_datepicker", text="", icon="OUTLINER_DATA_CAMERA")
                op.rule_index = index  # ✅ ESTO ES CRUCIAL - pasar el índice
            else:  # Por defecto, usar string (para texto, enums, etc.)
                value_row.prop(item, "value_string", text="")


class BIM_UL_saved_filter_sets(UIList):

    """Dibuja la lista de conjuntos de filtros guardados."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        # 'item' es una instancia de SavedFilterSet
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='FILTER')

class BIM_UL_task_inputs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row(align=True)
            op = row.operator("bim.select_product", text="", icon="RESTRICT_SELECT_OFF")
            op.product = item.ifc_definition_id
            row.prop(item, "name", emboss=False, text="")
            # row.operator("bim.remove_task_column", text="", icon="X").name = item.name


class BIM_UL_task_resources(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row(align=True)
            row.operator("bim.go_to_resource", text="", icon="STYLUS_PRESSURE").resource = item.ifc_definition_id
            row.prop(item, "name", emboss=False, text="")
            row.prop(item, "schedule_usage", emboss=False, text="")


class BIM_UL_animation_colors(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row()
            row.prop(item, "color", text="")
            row.prop(item, "name", text="")


class BIM_UL_task_outputs(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row(align=True)
            op = row.operator("bim.select_product", text="", icon="RESTRICT_SELECT_OFF")
            op.product = item.ifc_definition_id
            row.prop(item, "name", emboss=False, text="")


class BIM_UL_product_input_tasks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row(align=True)
            op = row.operator("bim.go_to_task", text="", icon="STYLUS_PRESSURE")
            op.task = item.ifc_definition_id
            row.split(factor=0.8)
            row.prop(item, "name", text="")


class BIM_UL_product_output_tasks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if item:
            row = layout.row(align=True)
            op = row.operator("bim.go_to_task", text="", icon="STYLUS_PRESSURE")
            op.task = item.ifc_definition_id
            row.split(factor=0.8)
            row.prop(item, "name", text="")


class BIM_UL_tasks(UIList):
    @classmethod
    def draw_header(cls, layout: bpy.types.UILayout):
        props = tool.Sequence.get_work_schedule_props()
        row = layout.row(align=True)


        split1 = row.split(factor=0.1)
        # Header "ID" + quick sort-by-ID button
        hdr = split1.row(align=True)
        hdr.label(text="ID", icon="BLANK1")
        hdr.operator("bim.sort_schedule_by_id_asc", text="", icon="SORTALPHA")
        split2 = split1.split(factor=0.9 - min(0.5, 0.15 * len(props.columns)))
        split2.label(text="Name")
        cls.draw_custom_columns(props, split2, header=True)

        # --- Outputs column header ---
        row.label(text="Outputs 3D")


    def draw_item(
        self,
        context,
        layout: bpy.types.UILayout,
        data: "BIMTaskTreeProperties",
        item: "Task",
        icon,
        active_data,
        active_propname,
    ):
        if item:
            self.props = tool.Sequence.get_work_schedule_props()
            task = SequenceData.data["tasks"][item.ifc_definition_id]
            row = layout.row(align=True)

            self.draw_hierarchy(row, item)

            split1 = row.split(factor=0.1)
            split1.prop(item, "identification", emboss=False, text="")
            split2 = split1.split(factor=0.9 - min(0.5, 0.15 * len(self.props.columns)))
            split2.prop(item, "name", emboss=False, text="")

            BIM_UL_tasks.draw_custom_columns(self.props, split2, item, task)

            # Show outputs count value


            row.label(text=str(item.outputs_count))

            if self.props.active_task_id and self.props.editing_task_type == "ATTRIBUTES":
                row.prop(
                    item,
                    "is_selected",
                    icon="CHECKBOX_HLT" if item.is_selected else "CHECKBOX_DEHLT",
                    text="",
                    emboss=False,
                )
            if self.props.should_show_task_bar_selection:
                row.prop(
                    item,
                    "has_bar_visual",
                    icon="COLLECTION_COLOR_04" if item.has_bar_visual else "OUTLINER_COLLECTION",
                    text="",
                    emboss=False,
                )
            if self.props.enable_reorder:
                self.draw_order_operator(row, item.ifc_definition_id)
            if self.props.editing_task_type == "SEQUENCE" and self.props.highlighted_task_id != item.ifc_definition_id:
                if item.is_predecessor:
                    op = row.operator("bim.unassign_predecessor", text="", icon="BACK", emboss=False)
                else:
                    op = row.operator("bim.assign_predecessor", text="", icon="TRACKING_BACKWARDS", emboss=False)
                op.task = item.ifc_definition_id

                if item.is_successor:
                    op = row.operator("bim.unassign_successor", text="", icon="FORWARD", emboss=False)
                else:
                    op = row.operator("bim.assign_successor", text="", icon="TRACKING_FORWARDS", emboss=False)
                op.task = item.ifc_definition_id

    def draw_order_operator(self, row: bpy.types.UILayout, ifc_definition_id: int) -> None:
        task = SequenceData.data["tasks"][ifc_definition_id]
        if task["NestingIndex"] is not None:
            if task["NestingIndex"] == 0:
                op = row.operator("bim.reorder_task_nesting", icon="TRIA_DOWN", text="")
                op.task = ifc_definition_id
                op.new_index = task["NestingIndex"] + 1
            elif task["NestingIndex"] > 0:
                op = row.operator("bim.reorder_task_nesting", icon="TRIA_UP", text="")
                op.task = ifc_definition_id
                op.new_index = task["NestingIndex"] - 1

    def draw_hierarchy(self, row: bpy.types.UILayout, item: bpy.types.PropertyGroup) -> None:
        for i in range(0, item.level_index):
            row.label(text="", icon="BLANK1")
        if item.has_children:
            if item.is_expanded:
                row.operator("bim.contract_task", text="", emboss=False, icon="DISCLOSURE_TRI_DOWN").task = (
                    item.ifc_definition_id
                )
            else:
                row.operator("bim.expand_task", text="", emboss=False, icon="DISCLOSURE_TRI_RIGHT").task = (
                    item.ifc_definition_id
                )
        else:
            row.label(text="", icon="DOT")

    @classmethod
    def draw_custom_columns(
        cls,
        props: bpy.types.PropertyGroup,
        row: bpy.types.UILayout,
        item: Optional[bpy.types.PropertyGroup] = None,
        task: Optional[dict[str, Any]] = None,
        *,
        header: bool = False,
    ) -> None:
        if not header:
            assert item and task

        for column in props.columns:
            if column.name == "IfcTaskTime.ScheduleStart":
                if header:
                    row.label(text="Start")
                else:
                    if item.derived_start:
                        row.label(text=item.derived_start + "*")
                    else:
                        row.prop(item, "start", emboss=False, text="")
            elif column.name == "IfcTaskTime.ScheduleFinish":
                if header:
                    row.label(text="Finish")
                else:
                    if item.derived_finish:
                        row.label(text=item.derived_finish + "*")
                    else:
                        row.prop(item, "finish", emboss=False, text="")
            elif column.name == "IfcTaskTime.ScheduleDuration":
                if header:
                    row.label(text="Duration")
                else:
                    if item.derived_duration:
                        row.label(text=item.derived_duration + "*")
                    else:
                        row.prop(item, "duration", emboss=False, text="")
            elif column.name == "Controls.Calendar":
                if header:
                    row.label(text="Calendar")
                else:
                    if item.derived_calendar:
                        row.label(text=item.derived_calendar + "*")
                    else:
                        row.label(text=item.calendar or "-")
            else:
                ifc_class, name = column.name.split(".")
                if header:
                    row.label(text=name)
                else:
                    if ifc_class == "IfcTask":
                        value = task[name]
                    elif ifc_class == "IfcTaskTime":
                        if (task_time_id := task["TaskTime"]) is None:
                            value = None
                        else:
                            value = SequenceData.data["task_times"][task_time_id][name]
                    else:
                        assert False, f"Unexpected ifc_class '{ifc_class}'."
                    if value is None:
                        value = "-"
                    else:
                        row.label(text=str(value))


class BIM_PT_work_calendars(Panel):
    bl_label = "Work Calendars"
    bl_idname = "BIM_PT_work_calendars"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"

    @classmethod
    def poll(cls, context):
        file = tool.Ifc.get()
        return file and hasattr(file, "schema") and file.schema != "IFC2X3"

    layout: bpy.types.UILayout

    def draw(self, context):
        if not SequenceData.is_loaded:
            SequenceData.load()

        self.props = tool.Sequence.get_work_calendar_props()
        row = self.layout.row()
        if SequenceData.data["has_work_calendars"]:
            row.label(
                text="{} Work Calendars Found".format(SequenceData.data["number_of_work_calendars_loaded"]),
                icon="TEXT",
            )
        else:
            row.label(text="No Work Calendars found.", icon="TEXT")
        row.operator("bim.add_work_calendar", icon="ADD", text="")
        for work_calendar_id, work_calendar in SequenceData.data["work_calendars"].items():
            self.draw_work_calendar_ui(work_calendar_id, work_calendar)

    def draw_work_calendar_ui(self, work_calendar_id, work_calendar):
        row = self.layout.row(align=True)
        row.label(text=work_calendar["Name"] or "Unnamed", icon="VIEW_ORTHO")
        if self.props.active_work_calendar_id == work_calendar_id:
            if self.props.editing_type == "ATTRIBUTES":
                row.operator("bim.edit_work_calendar", icon="CHECKMARK")
            row.operator("bim.disable_editing_work_calendar", text="", icon="CANCEL")
        elif self.props.active_work_calendar_id:
            row.operator("bim.remove_work_calendar", text="", icon="X").work_calendar = work_calendar_id
        else:
            op = row.operator("bim.enable_editing_work_calendar_times", text="", icon="MESH_GRID")
            op.work_calendar = work_calendar_id
            op = row.operator("bim.enable_editing_work_calendar", text="", icon="GREASEPENCIL")
            op.work_calendar = work_calendar_id
            row.operator("bim.remove_work_calendar", text="", icon="X").work_calendar = work_calendar_id

        if self.props.active_work_calendar_id == work_calendar_id:
            if self.props.editing_type == "ATTRIBUTES":
                self.draw_editable_ui()
            elif self.props.editing_type == "WORKTIMES":
                self.draw_work_times_ui(work_calendar_id, work_calendar)

    def draw_work_times_ui(self, work_calendar_id, work_calendar):
        row = self.layout.row(align=True)
        op = row.operator("bim.add_work_time", text="Add Work Time", icon="ADD")
        op.work_calendar = work_calendar_id
        op.time_type = "WorkingTimes"
        op = row.operator("bim.add_work_time", text="Add Exception Time", icon="ADD")
        op.work_calendar = work_calendar_id
        op.time_type = "ExceptionTimes"

        for work_time_id in work_calendar["WorkingTimes"]:
            self.draw_work_time_ui(SequenceData.data["work_times"][work_time_id], time_type="WorkingTimes")

        for work_time_id in work_calendar["ExceptionTimes"]:
            self.draw_work_time_ui(SequenceData.data["work_times"][work_time_id], time_type="ExceptionTimes")

    def draw_work_time_ui(self, work_time, time_type):
        row = self.layout.row(align=True)
        row.label(text=work_time["Name"] or "Unnamed", icon="AUTO" if time_type == "WorkingTimes" else "HOME")
        if work_time["Start"] or work_time["Finish"]:
            row.label(text="{} - {}".format(work_time["Start"] or "*", work_time["Finish"] or "*"))
        if self.props.active_work_time_id == work_time["id"]:
            row.operator("bim.edit_work_time", text="", icon="CHECKMARK")
            row.operator("bim.disable_editing_work_time", text="Cancel", icon="CANCEL")
        elif self.props.active_work_time_id:
            op = row.operator("bim.remove_work_time", text="", icon="X")
            op.work_time = work_time["id"]
        else:
            op = row.operator("bim.enable_editing_work_time", text="", icon="GREASEPENCIL")
            op.work_time = work_time["id"]
            op = row.operator("bim.remove_work_time", text="", icon="X")
            op.work_time = work_time["id"]

        if self.props.active_work_time_id == work_time["id"]:
            self.draw_editable_work_time_ui(work_time)

    def draw_editable_work_time_ui(self, work_time: dict[str, Any]) -> None:
        draw_attributes(self.props.work_time_attributes, self.layout)
        if work_time["RecurrencePattern"]:
            self.draw_editable_recurrence_pattern_ui(
                SequenceData.data["recurrence_patterns"][work_time["RecurrencePattern"]]
            )
        else:
            row = self.layout.row(align=True)
            row.prop(self.props, "recurrence_types", icon="RECOVER_LAST", text="")
            op = row.operator("bim.assign_recurrence_pattern", icon="ADD", text="")
            op.work_time = work_time["id"]
            op.recurrence_type = self.props.recurrence_types

    def draw_editable_recurrence_pattern_ui(self, recurrence_pattern):
        box = self.layout.box()
        row = box.row(align=True)
        row.label(text=recurrence_pattern["RecurrenceType"], icon="RECOVER_LAST")
        op = row.operator("bim.unassign_recurrence_pattern", text="", icon="X")
        op.recurrence_pattern = recurrence_pattern["id"]

        row = box.row(align=True)
        row.prop(self.props, "start_time", text="")
        row.prop(self.props, "end_time", text="")
        op = row.operator("bim.add_time_period", text="", icon="ADD")
        op.recurrence_pattern = recurrence_pattern["id"]

        for time_period_id in recurrence_pattern["TimePeriods"]:
            time_period = SequenceData.data["time_periods"][time_period_id]
            row = box.row(align=True)
            row.label(text="{} - {}".format(time_period["StartTime"], time_period["EndTime"]), icon="TIME")
            op = row.operator("bim.remove_time_period", text="", icon="X")
            op.time_period = time_period_id

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

        if "Position" in applicable_data[recurrence_pattern["RecurrenceType"]]:
            row = box.row()
            row.prop(self.props, "position")

        if "DayComponent" in applicable_data[recurrence_pattern["RecurrenceType"]]:
            for i, component in enumerate(self.props.day_components):
                if i % 7 == 0:
                    row = box.row(align=True)
                row.prop(component, "is_specified", text=component.name)

        if "WeekdayComponent" in applicable_data[recurrence_pattern["RecurrenceType"]]:
            row = box.row(align=True)
            for component in self.props.weekday_components:
                row.prop(component, "is_specified", text=component.name)

        if "MonthComponent" in applicable_data[recurrence_pattern["RecurrenceType"]]:
            for i, component in enumerate(self.props.month_components):
                if i % 4 == 0:
                    row = box.row(align=True)
                row.prop(component, "is_specified", text=component.name)

        row = box.row()
        row.prop(self.props, "interval")
        row = box.row()
        row.prop(self.props, "occurrences")

    def draw_editable_ui(self):
        draw_attributes(self.props.work_calendar_attributes, self.layout)


class BIM_PT_4D_Tools(Panel):
    bl_label = "4D Tools"
    bl_idname = "BIM_PT_4D_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"
    bl_order = 5
    def draw(self, context):
        self.props = tool.Sequence.get_work_schedule_props()

        # --- Active Work Schedule Info ---
        row = self.layout.row()
        try:
            if self.props.active_work_schedule_id:
                file = tool.Ifc.get()
                if file:
                    ws = file.by_id(self.props.active_work_schedule_id)
                    if ws:
                        row.label(text=f"Active Schedule: {getattr(ws, 'Name', None) or 'Unnamed'}", icon="TIME")
                    else:
                        row.label(text="No valid schedule selected", icon="ERROR")
                else:
                    row.label(text="No IFC file loaded", icon="ERROR")
            else:
                row.label(text="No schedule selected", icon="INFO")
        except Exception:
            row.label(text="No valid schedule selected", icon="ERROR")

        # --- Actions ---
        row = self.layout.row()
        row.operator("bim.load_product_related_tasks", text="Load Tasks", icon="FILE_REFRESH")
        row.prop(self.props, "filter_by_active_schedule", text="Filter by Active Schedule")

        # --- Lists ---
        grid = self.layout.grid_flow(columns=2, even_columns=True)
        col1 = grid.column()
        col1.label(text="Product Input Tasks")
        col1.template_list(
            "BIM_UL_product_input_tasks",
            "",
            self.props,
            "product_input_tasks",
            self.props,
            "active_product_input_task_index",
        )

        col2 = grid.column()
        col2.label(text="Product Output Tasks")
        col2.template_list(
            "BIM_UL_product_output_tasks",
            "",
            self.props,
            "product_output_tasks",
            self.props,
            "active_product_output_task_index",
        )


class BIM_PT_appearance_profiles(Panel):
    bl_label = "Appearance Profiles"
    bl_idname = "BIM_PT_appearance_profiles"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_sequence"

    bl_order = 4
    @classmethod
    def poll(cls, context):
        file = tool.Ifc.get()
        return file and hasattr(file, "schema") and file.schema != "IFC2X3"

    def draw(self, context):
        layout = self.layout
        props = tool.Sequence.get_animation_props()
        row = layout.row()
        row.template_list(
            "UI_UL_list", "appearance_profiles_list",
            props, "profiles",
            props, "active_profile_index"
        )

        col = row.column(align=True)
        col.operator("bim.add_appearance_profile", icon='ADD', text="")
        col.operator("bim.remove_appearance_profile", icon='REMOVE', text="")
        col.separator()  # Añadir separador visual
        col.operator("bim.load_appearance_profile_set_internal", icon='FILE_TICK', text="")

        if props.profiles and props.active_profile_index < len(props.profiles):
            p = props.profiles[props.active_profile_index]
            # --- Saved Sets (Internal) ---
            box = layout.box()
            row = box.row(align=True)
            row.operator("bim.save_appearance_profile_set_internal", icon='ADD', text="Save Set")
            row.operator("bim.update_active_profile_group", icon='FILE_REFRESH', text="Update Group")
            row.operator("bim.cleanup_task_profile_mappings", icon='BRUSH_DATA', text="Clean Tasks")
            # REMOVIDO: Load Set (ahora está arriba junto al botón -)
            row.operator("bim.remove_appearance_profile_set_internal", icon='TRASH', text="Remove Set")
            row.operator("bim.import_appearance_profile_set_from_file", icon='IMPORT', text="")
            row.operator("bim.export_appearance_profile_set_to_file", icon='EXPORT', text="")
            box = layout.box()
            box.prop(p, "name")

            # === Estados a considerar con documentación mejorada ===
            row = layout.row(align=True)
            row.label(text="Estados a considerar:")

            # MEJORA: Agregar tooltips explicativos
            start_row = row.row(align=True)
            start_row.prop(p, "consider_start", text="Start", toggle=True)
            if p.consider_start:
                start_row.label(text="", icon='INFO')

            row.prop(p, "consider_active", text="Active", toggle=True)
            row.prop(p, "consider_end", text="End", toggle=True)

            # NUEVA: Información sobre consider_start
            if p.consider_start:
                info_box = layout.box()
                info_box.label(text="ℹ️  Start Mode: Elements will maintain start appearance", icon='INFO')
                info_box.label(text="   throughout the entire animation, ignoring task dates.")
                info_box.label(text="   Useful for: existing elements, demolition context.")

            # --- Start Appearance ---
            start_box = layout.box()
            header = start_box.row(align=True)
            header.label(text="Start Appearance", icon='PLAY')
            col = start_box.column()
            col.enabled = bool(getattr(p, "consider_start", True))
            row = col.row(align=True)
            row.prop(p, "use_start_original_color")
            if not p.use_start_original_color:
                col.prop(p, "start_color")
            col.prop(p, "start_transparency")

            # --- Active / In Progress Appearance ---
            active_box = layout.box()
            header = active_box.row(align=True)
            header.label(text="Active Appearance", icon='SEQUENCE')
            col = active_box.column()
            col.enabled = bool(getattr(p, "consider_active", True))
            row = col.row(align=True)
            row.prop(p, "use_active_original_color")
            if not p.use_active_original_color:
                if hasattr(p, "in_progress_color"):
                    col.prop(p, "in_progress_color")
                elif hasattr(p, "active_color"):
                    col.prop(p, "active_color")
            col.prop(p, "active_start_transparency")
            col.prop(p, "active_finish_transparency")
            col.prop(p, "active_transparency_interpol")

            # --- End Appearance ---
            end_box = layout.box()
            header = end_box.row(align=True)
            header.label(text="End Appearance", icon='FF')
            col = end_box.column()
            col.enabled = bool(getattr(p, "consider_end", True))

            # <-- INICIO DE LA MODIFICACIÓN -->
            # Añadir el nuevo interruptor para ocultar al final
            col.prop(p, "hide_at_end")

            # Deshabilitar las siguientes opciones si "Hide When Finished" está activado
            row_original = col.row(align=True)
            row_original.enabled = not p.hide_at_end
            row_original.prop(p, "use_end_original_color")

            if not p.use_end_original_color:
                row_color = col.row(align=True)
                row_color.enabled = not p.hide_at_end
                row_color.prop(p, "end_color")

            row_transparency = col.row(align=True)
            row_transparency.enabled = not p.hide_at_end
            row_transparency.prop(p, "end_transparency")
            # <-- FIN DE LA MODIFICACIÓN -->


class BIM_PT_schedule_display(Panel):
    bl_label = "Schedule Display"
    bl_idname = "BIM_PT_schedule_display"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_animation_tools"

    @classmethod
    def poll(cls, context):
        try:
            import bpy
            return "Schedule_Display_Texts" in bpy.data.collections
        except Exception:
            return False

    def draw(self, context):
        import bpy
        layout = self.layout
        collection = bpy.data.collections.get("Schedule_Display_Texts")
        if not collection or not collection.objects:
            layout.label(text="No display texts found", icon='INFO')
            return
        for text_obj in collection.objects:
            box = layout.box()
            row = box.row(align=True)
            text_type = text_obj.data.get("text_type", "unknown")
            icon_map = {"date": "TIME","week": "COLLAPSEMENU","day_counter": "SORTTIME","progress": "STATUSBAR"}
            row.label(text=text_type.replace("_", " ").title(), icon=icon_map.get(text_type, "FONT_DATA"))
            row.prop(text_obj, "hide_viewport", text="", icon='HIDE_OFF', emboss=False)
            col = box.column(align=True)
            col.prop(text_obj, "location", text="Position")
            try:
                col.prop(text_obj.data, "size", text="Size")
            except Exception:
                pass
            if text_obj.data.materials:
                mat = text_obj.data.materials[0]
                if getattr(mat, "use_nodes", False) and mat.node_tree:
                    bsdf = mat.node_tree.nodes.get("Principled BSDF")
                    if bsdf:
                        col.prop(bsdf.inputs["Base Color"], "default_value", text="Color")
        row = layout.row(align=True)
        row.operator("bim.arrange_schedule_texts", text="Auto-Arrange", icon="ALIGN_TOP")



# --- Auto-registration for UI panels in this module ---
def register():
    import bpy
    # Register all Panel subclasses defined here
    for _name, _cls in list(globals().items()):
        try:
            if isinstance(_cls, type) and issubclass(_cls, bpy.types.Panel):
                bpy.utils.register_class(_cls)
        except Exception:
            pass

def unregister():
    import bpy
    # Unregister in reverse order
    for _name, _cls in list(globals().items())[::-1]:
        try:
            if isinstance(_cls, type) and issubclass(_cls, bpy.types.Panel):
                bpy.utils.unregister_class(_cls)
        except Exception:
            pass
