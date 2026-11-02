// Weekly Off / Rest Day on the Shift Assignment form (thinkNXG ESS Portal).
frappe.ui.form.on("Shift Assignment", {
	refresh(frm) {
		frm.toggle_reqd("end_date", !!frm.doc.ess_weekly_off);
		if (frm.doc.ess_weekly_off && frm.doc.docstatus === 0) {
			frm.set_intro(__("Every date from Start Date to End Date will be added to the employee's holiday list as \"Weekly Off\" when you submit."), "blue");
		}
	},
	async ess_weekly_off(frm) {
		frm.toggle_reqd("end_date", !!frm.doc.ess_weekly_off);
		if (!frm.doc.ess_weekly_off) return;
		const name = (await frappe.db.get_single_value("ESS Portal Settings", "weekly_off_shift_type")) || "Weekly Off";
		if (frm.doc.shift_type !== name) frm.set_value("shift_type", name);
	},
	async shift_type(frm) {
		if (!frm.doc.shift_type) return;
		const r = await frappe.db.get_value("Shift Type", frm.doc.shift_type, "ess_weekly_off");
		const wo = r && r.message && r.message.ess_weekly_off ? 1 : 0;
		if (wo !== (frm.doc.ess_weekly_off || 0)) frm.set_value("ess_weekly_off", wo);
	},
});
