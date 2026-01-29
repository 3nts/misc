# /// script
# requires-python = ">=3.14"
# dependencies = ["google-cloud-asset", "google-cloud-recommender"]
# ///
"""
GCP Project Cleanup Report

Usage: uv run gcp_project_cleanup.py ORG_ID [--show-inactive]
"""

import argparse

from google.cloud import asset_v1
from google.cloud.recommender_v1 import RecommenderClient


def fetch_projects(org_id):
    client = asset_v1.AssetServiceClient()
    response = client.search_all_resources(
        scope=f"organizations/{org_id}",
        asset_types=["cloudresourcemanager.googleapis.com/Project"],
    )

    projects = []
    for r in response:
        _, project_id = r.name.rsplit("/projects/", 1)
        _, project_number = r.project.rsplit("/", 1)

        projects.append(
            {
                "project_id": project_id,
                "project_number": project_number,
                "display_name": r.display_name,
                "create_date": str(r.create_time.date()),
            }
        )
    return projects


def fetch_project_owners(org_id):
    client = asset_v1.AssetServiceClient()
    response = client.search_all_iam_policies(
        scope=f"organizations/{org_id}",
        query="policy:roles/owner",
    )

    owners = {}
    for policy in response:
        project_id = policy.resource.split("/projects/")[-1].split("/")[0]

        for binding in policy.policy.bindings:
            if binding.role == "roles/owner":
                usernames = [
                    m.removeprefix("user:").split("@")[0]
                    for m in binding.members
                    if m.startswith("user:")
                ]
                owners.setdefault(project_id, []).extend(usernames)

    for project_id in owners:
        owners[project_id] = list(set(owners[project_id]))

    return owners


def fetch_inactive_project_numbers(org_id):
    client = RecommenderClient()
    recommendations = client.list_recommendations(
        parent=f"organizations/{org_id}/locations/global/recommenders/google.resourcemanager.projectUtilization.Recommender"
    )

    inactive = set()
    for rec in recommendations:
        for group in rec.content.operation_groups:
            for op in group.operations:
                if "/projects/" in op.resource:
                    project_number = op.resource.split("/projects/")[-1].split("/")[0]
                    inactive.add(project_number)

    return inactive


def print_report(projects, show_inactive):
    headers = ["display_name", "owners", "create_date", "project_id"]
    if show_inactive:
        headers.append("inactive")

    display_data = []
    for p in projects:
        owners_str = ", ".join(sorted(p["owners"])) if p["owners"] else "-"
        row = {
            "display_name": p["display_name"],
            "owners": owners_str,
            "create_date": p["create_date"],
            "project_id": p["project_id"],
        }
        if show_inactive:
            row["inactive"] = str(p["inactive"])
        display_data.append(row)

    col_widths = {}
    for col in headers:
        col_widths[col] = max(len(col), max(len(row[col]) for row in display_data))

    header_row = "  ".join(h.ljust(col_widths[h]) for h in headers)
    print(header_row)
    print("-" * len(header_row))

    for row in display_data:
        print("  ".join(row[h].ljust(col_widths[h]) for h in headers))


def main():
    parser = argparse.ArgumentParser(description="GCP Project Cleanup Report")
    parser.add_argument("org_id", metavar="ORG_ID", help="GCP organization ID")
    parser.add_argument(
        "--show-inactive",
        action="store_true",
        help="show inactive column (default: hidden)",
    )
    args = parser.parse_args()

    projects = fetch_projects(args.org_id)
    owners = fetch_project_owners(args.org_id)
    inactive = fetch_inactive_project_numbers(args.org_id)

    for p in projects:
        p["owners"] = owners.get(p["project_id"], [])
        p["inactive"] = p["project_number"] in inactive

    projects.sort(key=lambda p: (not p["inactive"], p["create_date"]))

    print_report(projects, args.show_inactive)


if __name__ == "__main__":
    main()
