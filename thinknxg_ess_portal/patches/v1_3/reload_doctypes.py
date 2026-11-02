"""Releases before v1.3 shipped every DocType with the same `modified` timestamp, so `bench migrate` skipped the new
fields added in v1.2/v1.3 (ESS Portal Settings, ESS Roster Entry). Force-reload all ESS DocTypes once, then re-run
the install steps (custom fields, Weekly Off shift type, settings defaults)."""
import os

import frappe


def execute():
    base = frappe.get_app_path("thinknxg_ess_portal", "ess_portal", "doctype")
    for folder in sorted(os.listdir(base)):
        if os.path.isfile(os.path.join(base, folder, f"{folder}.json")):
            frappe.reload_doc("ess_portal", "doctype", folder, force=True)
    frappe.clear_cache()
    from thinknxg_ess_portal.install import after_migrate
    after_migrate()
