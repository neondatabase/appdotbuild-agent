#!/usr/bin/env python3
"""
Generate HTML viewer with dropdown to select from archived evaluations.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime


def find_archived_reports() -> list[dict]:
    """Scan archive folder for past evaluation reports."""
    archive_dir = Path(__file__).parent.parent / "archive"
    reports = []

    if not archive_dir.exists():
        return reports

    # Scan archive subdirectories
    for archive_subdir in sorted(archive_dir.iterdir(), reverse=True):
        if not archive_subdir.is_dir():
            continue

        # Look for evaluation_report.json in app-eval or root
        report_paths = [
            archive_subdir / "app-eval" / "evaluation_report.json",
            archive_subdir / "evaluation_report.json",
        ]

        for report_path in report_paths:
            if report_path.exists():
                try:
                    with open(report_path) as f:
                        data = json.load(f)

                    # Extract metadata
                    timestamp = data.get("summary", {}).get("timestamp", archive_subdir.name)
                    total_apps = data.get("summary", {}).get("total_apps", 0)

                    reports.append({
                        "id": archive_subdir.name,
                        "timestamp": timestamp,
                        "path": str(report_path.relative_to(archive_dir.parent)),
                        "total_apps": total_apps,
                        "data": data
                    })
                    break
                except Exception:
                    continue

    return reports


def generate_html_viewer():
    """Generate HTML viewer with archived reports selector."""

    # Find all archived reports
    archived_reports = find_archived_reports()

    # Also check for latest results
    latest_reports = []
    project_root = Path(__file__).parent.parent

    # Check results_latest
    results_latest = project_root / "results_latest"
    if results_latest.exists() and results_latest.is_symlink():
        for mode in ["vanilla", "mcp"]:
            report_path = results_latest / mode / "evaluation_report.json"
            if report_path.exists():
                try:
                    with open(report_path) as f:
                        data = json.load(f)
                    latest_reports.append({
                        "id": f"latest_{mode}",
                        "timestamp": data.get("summary", {}).get("timestamp", ""),
                        "path": str(report_path.relative_to(project_root)),
                        "mode": mode,
                        "data": data
                    })
                except Exception:
                    continue

    # Generate reports list for JavaScript
    all_reports = latest_reports + archived_reports
    reports_json = json.dumps(all_reports, indent=2)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Klaudbiusz Evaluation Viewer</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 30px;
        }}

        .header {{
            margin-bottom: 30px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 20px;
        }}

        h1 {{
            color: #333;
            font-size: 28px;
            margin-bottom: 10px;
        }}

        .controls {{
            display: flex;
            gap: 20px;
            align-items: center;
            margin-bottom: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 6px;
        }}

        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}

        label {{
            font-weight: 600;
            color: #555;
            font-size: 14px;
        }}

        select {{
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            min-width: 300px;
            background: white;
            cursor: pointer;
        }}

        select:hover {{
            border-color: #999;
        }}

        .report-info {{
            background: #e3f2fd;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border-left: 4px solid #2196f3;
        }}

        .report-info p {{
            margin: 5px 0;
            color: #333;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .metric-card h3 {{
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .metric-value {{
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 5px;
        }}

        .metric-detail {{
            font-size: 14px;
            opacity: 0.8;
        }}

        .apps-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}

        .apps-table th {{
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #555;
            border-bottom: 2px solid #ddd;
        }}

        .apps-table td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}

        .apps-table tr:hover {{
            background: #f9f9f9;
        }}

        .status-badge {{
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
        }}

        .status-pass {{
            background: #d4edda;
            color: #155724;
        }}

        .status-fail {{
            background: #f8d7da;
            color: #721c24;
        }}

        .status-na {{
            background: #e2e3e5;
            color: #383d41;
        }}

        .score {{
            font-weight: 600;
            color: #333;
        }}

        h2 {{
            color: #333;
            margin: 30px 0 15px 0;
            padding-bottom: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}

        .no-report {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }}

        .no-report h2 {{
            border: none;
            color: #999;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Klaudbiusz Evaluation Viewer</h1>
            <p style="color: #666; margin-top: 8px;">View and compare AI-generated application evaluations</p>
        </div>

        <div class="controls">
            <div class="control-group">
                <label for="report-select">Select Evaluation Report:</label>
                <select id="report-select">
                    <option value="">-- Select a report --</option>
                </select>
            </div>
        </div>

        <div id="report-container">
            <div class="no-report">
                <h2>No report selected</h2>
                <p>Select an evaluation report from the dropdown above</p>
            </div>
        </div>
    </div>

    <script>
        // All available reports (pre-populated from archive)
        const reports = {reports_json};

        // Populate dropdown
        const select = document.getElementById('report-select');
        reports.forEach(report => {{
            const option = document.createElement('option');
            option.value = report.id;

            let label = report.timestamp || report.id;
            if (report.mode) {{
                label += ` (Mode: ${{report.mode}})`;
            }}
            if (report.total_apps) {{
                label += ` - ${{report.total_apps}} apps`;
            }}

            option.textContent = label;
            select.appendChild(option);
        }});

        // Handle selection change
        select.addEventListener('change', (e) => {{
            const reportId = e.target.value;
            if (!reportId) {{
                document.getElementById('report-container').innerHTML = `
                    <div class="no-report">
                        <h2>No report selected</h2>
                        <p>Select an evaluation report from the dropdown above</p>
                    </div>
                `;
                return;
            }}

            const report = reports.find(r => r.id === reportId);
            if (report) {{
                renderReport(report.data);
            }}
        }});

        function renderReport(data) {{
            const summary = data.summary || {{}};
            const apps = data.apps || [];
            const metrics = summary.metrics_summary || {{}};

            let html = `
                <div class="report-info">
                    <p><strong>Timestamp:</strong> ${{summary.timestamp || 'N/A'}}</p>
                    <p><strong>Mode:</strong> ${{summary.mode || 'N/A'}}</p>
                    <p><strong>Total Apps:</strong> ${{summary.total_apps || 0}}</p>
                    <p><strong>Evaluated:</strong> ${{summary.evaluated || 0}}</p>
                </div>

                <h2>📊 Metrics Summary</h2>
                <div class="metrics-grid">
            `;

            // Render metric cards
            const metricNames = [
                ['build_success', 'Build Success'],
                ['runtime_success', 'Runtime Success'],
                ['type_safety', 'Type Safety'],
                ['tests_pass', 'Tests Pass'],
                ['databricks_connectivity', 'DB Connectivity'],
                ['ui_renders', 'UI Renders']
            ];

            metricNames.forEach(([key, label]) => {{
                const metric = metrics[key] || {{}};
                const pass = metric.pass || 0;
                const fail = metric.fail || 0;
                const total = pass + fail;
                const percentage = total > 0 ? Math.round((pass / total) * 100) : 0;

                html += `
                    <div class="metric-card">
                        <h3>${{label}}</h3>
                        <div class="metric-value">${{percentage}}%</div>
                        <div class="metric-detail">${{pass}}/${{total}} apps passed</div>
                    </div>
                `;
            }});

            html += `</div>`;

            // Render apps table
            html += `
                <h2>📱 Apps Evaluation Details</h2>
                <table class="apps-table">
                    <thead>
                        <tr>
                            <th>App Name</th>
                            <th>Build</th>
                            <th>Runtime</th>
                            <th>Type Safety</th>
                            <th>Tests</th>
                            <th>DB Connect</th>
                            <th>Local Run</th>
                            <th>Deploy</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            apps.forEach(app => {{
                const m = app.metrics || {{}};
                html += `
                    <tr>
                        <td><strong>${{app.app_name}}</strong></td>
                        <td>${{renderStatus(m.build_success)}}</td>
                        <td>${{renderStatus(m.runtime_success)}}</td>
                        <td>${{renderStatus(m.type_safety)}}</td>
                        <td>${{renderStatus(m.tests_pass)}}</td>
                        <td>${{renderStatus(m.databricks_connectivity)}}</td>
                        <td><span class="score">${{m.local_runability_score || 0}}/5</span></td>
                        <td><span class="score">${{m.deployability_score || 0}}/5</span></td>
                    </tr>
                `;
            }});

            html += `
                    </tbody>
                </table>
            `;

            document.getElementById('report-container').innerHTML = html;
        }}

        function renderStatus(value) {{
            if (value === true) {{
                return '<span class="status-badge status-pass">PASS</span>';
            }} else if (value === false) {{
                return '<span class="status-badge status-fail">FAIL</span>';
            }} else {{
                return '<span class="status-badge status-na">N/A</span>';
            }}
        }}

        // Auto-select first report if available
        if (reports.length > 0) {{
            select.value = reports[0].id;
            select.dispatchEvent(new Event('change'));
        }}
    </script>
</body>
</html>
"""

    # Write HTML file
    output_path = Path(__file__).parent.parent / "evaluation_viewer.html"
    with open(output_path, "w") as f:
        f.write(html_content)

    print(f"✅ Generated HTML viewer: {output_path}")
    print(f"📊 Found {len(all_reports)} evaluation reports")
    print(f"   - Latest: {len(latest_reports)}")
    print(f"   - Archived: {len(archived_reports)}")
    print(f"\n🌐 Open in browser: file://{output_path.absolute()}")


if __name__ == "__main__":
    generate_html_viewer()
