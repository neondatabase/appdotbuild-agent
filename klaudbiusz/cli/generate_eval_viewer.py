#!/usr/bin/env python3
"""Generate an interactive HTML viewer for evaluation reports."""

import json
from pathlib import Path
from datetime import datetime


def generate_html_viewer(eval_json_path: Path, output_path: Path):
    """Generate a standalone HTML viewer for evaluation results."""

    # read evaluation data
    with open(eval_json_path) as f:
        data = json.load(f)

    # embed the JSON data directly in the HTML
    json_data = json.dumps(data, indent=2)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Klaudbiusz Evaluation Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        .header .subtitle {{
            opacity: 0.9;
            font-size: 1.1em;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            padding: 40px;
            background: #f8f9fa;
        }}

        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
        }}

        .stat-card .label {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .stat-card .value {{
            font-size: 2.5em;
            font-weight: bold;
            color: #333;
        }}

        .stat-card .percentage {{
            font-size: 1em;
            color: #888;
            margin-top: 5px;
        }}

        .stat-card.success .value {{ color: #10b981; }}
        .stat-card.warning .value {{ color: #f59e0b; }}
        .stat-card.error .value {{ color: #ef4444; }}

        .section {{
            padding: 40px;
        }}

        .section-title {{
            font-size: 1.8em;
            margin-bottom: 20px;
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}

        .apps-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            font-size: 0.95em;
        }}

        .apps-table thead {{
            background: #667eea;
            color: white;
        }}

        .apps-table th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}

        .apps-table td {{
            padding: 12px 15px;
            border-bottom: 1px solid #e5e7eb;
        }}

        .apps-table tbody tr:hover {{
            background: #f3f4f6;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}

        .badge.success {{
            background: #d1fae5;
            color: #065f46;
        }}

        .badge.error {{
            background: #fee2e2;
            color: #991b1b;
        }}

        .badge.warning {{
            background: #fef3c7;
            color: #92400e;
        }}

        .quality-badge {{
            padding: 6px 14px;
            border-radius: 15px;
            font-weight: 600;
            font-size: 0.9em;
        }}

        .quality-excellent {{ background: #d1fae5; color: #065f46; }}
        .quality-good {{ background: #dbeafe; color: #1e40af; }}
        .quality-fair {{ background: #fef3c7; color: #92400e; }}
        .quality-poor {{ background: #fee2e2; color: #991b1b; }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}

        .metric-card {{
            background: white;
            border: 2px solid #e5e7eb;
            border-radius: 12px;
            padding: 20px;
        }}

        .metric-card h3 {{
            margin-bottom: 15px;
            color: #667eea;
        }}

        .metric-bar {{
            background: #e5e7eb;
            height: 30px;
            border-radius: 15px;
            overflow: hidden;
            position: relative;
        }}

        .metric-bar-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 1s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.9em;
        }}

        .filters {{
            display: flex;
            gap: 15px;
            margin: 20px 0;
            flex-wrap: wrap;
        }}

        .filter-btn {{
            padding: 10px 20px;
            border: 2px solid #667eea;
            background: white;
            color: #667eea;
            border-radius: 25px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.2s;
        }}

        .filter-btn:hover {{
            background: #667eea;
            color: white;
        }}

        .filter-btn.active {{
            background: #667eea;
            color: white;
        }}

        .search-box {{
            flex: 1;
            min-width: 250px;
            padding: 10px 20px;
            border: 2px solid #e5e7eb;
            border-radius: 25px;
            font-size: 1em;
        }}

        .search-box:focus {{
            outline: none;
            border-color: #667eea;
        }}

        .chart-container {{
            margin: 30px 0;
            padding: 20px;
            background: white;
            border-radius: 12px;
            border: 2px solid #e5e7eb;
        }}

        .issues-list {{
            margin-top: 20px;
        }}

        .issue-item {{
            padding: 15px;
            margin-bottom: 10px;
            background: #f9fafb;
            border-left: 4px solid #667eea;
            border-radius: 5px;
        }}

        .issue-item strong {{
            color: #667eea;
        }}

        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: 1fr;
            }}

            .apps-table {{
                font-size: 0.85em;
            }}

            .apps-table th,
            .apps-table td {{
                padding: 8px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Klaudbiusz Evaluation Report</h1>
            <p class="subtitle">AI-Generated Databricks Applications - Objective Quality Metrics</p>
            <p class="subtitle">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>

        <div class="stats-grid" id="statsGrid"></div>

        <div class="section">
            <h2 class="section-title">📊 9 Core Metrics Performance</h2>
            <div class="metrics-grid" id="metricsGrid"></div>
        </div>

        <div class="section">
            <h2 class="section-title">🎯 Quality Distribution</h2>
            <div class="chart-container" id="qualityChart"></div>
        </div>

        <div class="section">
            <h2 class="section-title">🚨 Most Common Issues</h2>
            <div class="issues-list" id="issuesList"></div>
        </div>

        <div class="section">
            <h2 class="section-title">📱 Applications Detail</h2>
            <div class="filters">
                <input type="text" class="search-box" id="searchBox" placeholder="🔍 Search apps...">
                <button class="filter-btn active" data-filter="all">All Apps</button>
                <button class="filter-btn" data-filter="success">✅ Build Success</button>
                <button class="filter-btn" data-filter="runtime">🏃 Runtime OK</button>
                <button class="filter-btn" data-filter="tests">✔️ Tests Pass</button>
                <button class="filter-btn" data-filter="issues">⚠️ Has Issues</button>
            </div>
            <div style="overflow-x: auto;">
                <table class="apps-table" id="appsTable">
                    <thead>
                        <tr>
                            <th>App Name</th>
                            <th>Quality</th>
                            <th>Build</th>
                            <th>Runtime</th>
                            <th>Types</th>
                            <th>Tests</th>
                            <th>DB</th>
                            <th>LOC</th>
                            <th>💰 Cost</th>
                            <th>🎯 Tokens</th>
                            <th>🔄 Turns</th>
                            <th>Issues</th>
                        </tr>
                    </thead>
                    <tbody id="appsTableBody"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Embed evaluation data
        const evalData = {json_data};

        // Debug: Log data structure
        console.log('Evaluation data loaded:', evalData);
        console.log('Summary:', evalData.summary);
        console.log('Metrics:', evalData.summary?.metrics_summary);
        console.log('Apps count:', evalData.apps?.length);

        // Render stats grid
        function renderStatsGrid() {{
            const stats = evalData.summary.metrics_summary || {{}};
            const genMetrics = evalData.summary.generation_metrics || {{}};
            const total = evalData.summary.total_apps || 0;

            // Helper function to safely format numbers
            const safe = (val, def = 0) => val !== undefined && val !== null ? val : def;
            const pct = (val) => ((safe(val) / total) * 100).toFixed(0);

            const statsHtml = `
                <div class="stat-card success">
                    <div class="label">Total Apps</div>
                    <div class="value">${{total}}</div>
                </div>
                <div class="stat-card ${{safe(stats.build_success) / total >= 0.8 ? 'success' : 'warning'}}">
                    <div class="label">Build Success</div>
                    <div class="value">${{safe(stats.build_success)}}</div>
                    <div class="percentage">${{pct(stats.build_success)}}%</div>
                </div>
                <div class="stat-card ${{safe(stats.runtime_success) / total >= 0.8 ? 'success' : 'warning'}}">
                    <div class="label">Runtime Success</div>
                    <div class="value">${{safe(stats.runtime_success)}}</div>
                    <div class="percentage">${{pct(stats.runtime_success)}}%</div>
                </div>
                <div class="stat-card ${{safe(stats.type_safety_pass) / total >= 0.5 ? 'success' : 'error'}}">
                    <div class="label">Type Safety</div>
                    <div class="value">${{safe(stats.type_safety_pass)}}</div>
                    <div class="percentage">${{pct(stats.type_safety_pass)}}%</div>
                </div>
                <div class="stat-card ${{safe(stats.tests_pass) / total >= 0.5 ? 'success' : 'error'}}">
                    <div class="label">Tests Pass</div>
                    <div class="value">${{safe(stats.tests_pass)}}</div>
                    <div class="percentage">${{pct(stats.tests_pass)}}%</div>
                </div>
                <div class="stat-card">
                    <div class="label">Avg LOC</div>
                    <div class="value">${{safe(stats.avg_loc || stats.avg_loc_per_app).toFixed(0)}}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Avg Build Time</div>
                    <div class="value">${{safe(stats.avg_build_time).toFixed(1)}}s</div>
                </div>
                <div class="stat-card">
                    <div class="label">Local Runability</div>
                    <div class="value">${{safe(stats.avg_local_runability || stats.local_runability_avg).toFixed(1)}}/5</div>
                    <div class="percentage">${{'⭐'.repeat(Math.round(safe(stats.avg_local_runability || stats.local_runability_avg)))}}</div>
                </div>
                <div class="stat-card" style="border: 2px solid #10b981;">
                    <div class="label">💰 Total Cost</div>
                    <div class="value">${{safe(genMetrics.total_cost_usd) > 0 ? '$' + safe(genMetrics.total_cost_usd).toFixed(2) : 'N/A'}}</div>
                    <div class="percentage">Avg: ${{safe(genMetrics.avg_cost_usd).toFixed(2)}}/app</div>
                </div>
                <div class="stat-card" style="border: 2px solid #3b82f6;">
                    <div class="label">🎯 Avg Output Tokens</div>
                    <div class="value">${{safe(genMetrics.avg_output_tokens) > 0 ? safe(genMetrics.avg_output_tokens).toFixed(0) : 'N/A'}}</div>
                    <div class="percentage">Per app</div>
                </div>
                <div class="stat-card" style="border: 2px solid #8b5cf6;">
                    <div class="label">🔄 Avg Turns</div>
                    <div class="value">${{safe(genMetrics.avg_turns) > 0 ? safe(genMetrics.avg_turns).toFixed(0) : 'N/A'}}</div>
                    <div class="percentage">${{safe(genMetrics.avg_tokens_per_turn) > 0 ? safe(genMetrics.avg_tokens_per_turn).toFixed(0) + ' tokens/turn' : ''}}</div>
                </div>
            `;

            document.getElementById('statsGrid').innerHTML = statsHtml;
        }}

        // Render metrics grid
        function renderMetricsGrid() {{
            const stats = evalData.summary.metrics_summary || {{}};
            const total = evalData.summary.total_apps || 0;

            // Helper for safe values
            const safe = (val, def = 0) => val !== undefined && val !== null ? val : def;

            const metrics = [
                {{ name: '1. Build Success', value: safe(stats.build_success), total }},
                {{ name: '2. Runtime Success', value: safe(stats.runtime_success), total }},
                {{ name: '3. Type Safety', value: safe(stats.type_safety_pass), total }},
                {{ name: '4. Tests Pass', value: safe(stats.tests_pass), total }},
                {{ name: '5. DB Connectivity', value: safe(stats.databricks_connectivity), total }},
                {{ name: '6. Data Returned', value: safe(stats.data_returned), total }},
                {{ name: '7. UI Renders', value: safe(stats.ui_renders), total }},
            ];

            const metricsHtml = metrics.map(m => {{
                const percentage = (m.value / m.total * 100).toFixed(0);
                return `
                    <div class="metric-card">
                        <h3>${{m.name}}</h3>
                        <div class="metric-bar">
                            <div class="metric-bar-fill" style="width: ${{percentage}}%">
                                ${{m.value}}/${{m.total}} (${{percentage}}%)
                            </div>
                        </div>
                    </div>
                `;
            }}).join('');

            document.getElementById('metricsGrid').innerHTML = metricsHtml;
        }}

        // Render quality chart
        function renderQualityChart() {{
            const dist = evalData.summary.quality_distribution;
            const total = evalData.summary.total_apps;

            // Handle both array and number formats
            const excellent = Array.isArray(dist.excellent) ? dist.excellent.length : dist.excellent;
            const good = Array.isArray(dist.good) ? dist.good.length : dist.good;
            const fair = Array.isArray(dist.fair) ? dist.fair.length : dist.fair;
            const poor = Array.isArray(dist.poor) ? dist.poor.length : dist.poor;

            const chartHtml = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;">
                    <div style="text-align: center;">
                        <div style="font-size: 3em; color: #10b981;">🟢</div>
                        <div style="font-size: 2em; font-weight: bold;">${{excellent}}</div>
                        <div style="color: #666;">Excellent (0 issues)</div>
                        <div style="color: #888;">${{(excellent / total * 100).toFixed(0)}}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 3em; color: #3b82f6;">🟡</div>
                        <div style="font-size: 2em; font-weight: bold;">${{good}}</div>
                        <div style="color: #666;">Good (1-2 issues)</div>
                        <div style="color: #888;">${{(good / total * 100).toFixed(0)}}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 3em; color: #f59e0b;">🟠</div>
                        <div style="font-size: 2em; font-weight: bold;">${{fair}}</div>
                        <div style="color: #666;">Fair (3-4 issues)</div>
                        <div style="color: #888;">${{(fair / total * 100).toFixed(0)}}%</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 3em; color: #ef4444;">🔴</div>
                        <div style="font-size: 2em; font-weight: bold;">${{poor}}</div>
                        <div style="color: #666;">Poor (5+ issues)</div>
                        <div style="color: #888;">${{(poor / total * 100).toFixed(0)}}%</div>
                    </div>
                </div>
            `;

            document.getElementById('qualityChart').innerHTML = chartHtml;
        }}

        // Render issues list
        function renderIssuesList() {{
            const issuesData = evalData.summary.common_issues || {{}};
            const total = evalData.summary.total_apps;

            // Convert object to array if needed
            let issues = [];
            if (Array.isArray(issuesData)) {{
                issues = issuesData;
            }} else {{
                issues = Object.entries(issuesData).map(([issue, count]) => ({{issue, count}}));
            }}

            const issuesHtml = issues.slice(0, 10).map(issue => `
                <div class="issue-item">
                    <strong>${{issue.issue}}</strong> -
                    ${{issue.count}} apps (${{(issue.count / total * 100).toFixed(0)}}%)
                </div>
            `).join('');

            document.getElementById('issuesList').innerHTML = issuesHtml || '<p>No issues reported</p>';
        }}

        // Render apps table
        function renderAppsTable(filterFn = () => true) {{
            const apps = evalData.apps.filter(filterFn);

            const getQualityBadge = (issueCount) => {{
                if (issueCount === 0) return '<span class="quality-badge quality-excellent">🟢 Excellent</span>';
                if (issueCount <= 2) return '<span class="quality-badge quality-good">🟡 Good</span>';
                if (issueCount <= 4) return '<span class="quality-badge quality-fair">🟠 Fair</span>';
                return '<span class="quality-badge quality-poor">🔴 Poor</span>';
            }};

            const tableHtml = apps.map(app => {{
                const m = app.metrics || {{}};
                const gen = app.generation_metrics || {{}};
                const issueCount = (app.issues || []).length;

                // Format generation metrics
                const cost = gen.cost_usd ? '$' + gen.cost_usd.toFixed(2) : '-';
                const tokens = gen.output_tokens ? gen.output_tokens.toLocaleString() : '-';
                const turns = gen.turns || '-';

                return `
                <tr>
                    <td><strong>${{app.app_name}}</strong></td>
                    <td>${{getQualityBadge(issueCount)}}</td>
                    <td>${{m.build_success ? '<span class="badge success">✅</span>' : '<span class="badge error">❌</span>'}}</td>
                    <td>${{m.runtime_success ? '<span class="badge success">✅</span>' : '<span class="badge error">❌</span>'}}</td>
                    <td>${{m.type_safety ? '<span class="badge success">✅</span>' : '<span class="badge error">❌</span>'}}</td>
                    <td>${{m.tests_pass ? '<span class="badge success">✅</span>' : '<span class="badge error">❌</span>'}}</td>
                    <td>${{m.databricks_connectivity ? '<span class="badge success">✅</span>' : '<span class="badge error">❌</span>'}}</td>
                    <td>${{m.total_loc || 0}}</td>
                    <td style="font-weight: 600; color: #10b981;">${{cost}}</td>
                    <td style="font-weight: 600; color: #3b82f6;">${{tokens}}</td>
                    <td style="font-weight: 600; color: #8b5cf6;">${{turns}}</td>
                    <td><span class="badge warning">${{issueCount}}</span></td>
                </tr>
            `}}).join('');

            document.getElementById('appsTableBody').innerHTML = tableHtml;
        }}

        // Setup filters
        function setupFilters() {{
            const filterBtns = document.querySelectorAll('.filter-btn');
            const searchBox = document.getElementById('searchBox');

            filterBtns.forEach(btn => {{
                btn.addEventListener('click', () => {{
                    filterBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');

                    const filter = btn.dataset.filter;
                    let filterFn = () => true;

                    if (filter === 'success') filterFn = app => app.metrics?.build_success;
                    else if (filter === 'runtime') filterFn = app => app.metrics?.runtime_success;
                    else if (filter === 'tests') filterFn = app => app.metrics?.tests_pass;
                    else if (filter === 'issues') filterFn = app => (app.issues || []).length > 0;

                    renderAppsTable(filterFn);
                }});
            }});

            searchBox.addEventListener('input', (e) => {{
                const query = e.target.value.toLowerCase();
                renderAppsTable(app => app.app_name.toLowerCase().includes(query));
            }});
        }}

        // Initialize
        renderStatsGrid();
        renderMetricsGrid();
        renderQualityChart();
        renderIssuesList();
        renderAppsTable();
        setupFilters();
    </script>
</body>
</html>
"""

    # Write HTML file
    output_path.write_text(html_content)
    print(f"✅ Generated HTML viewer: {output_path}")
    return output_path


def main():
    """Main entry point."""
    script_dir = Path(__file__).parent
    app_eval_dir = script_dir.parent / "app-eval"

    # Find the evaluation report JSON
    json_file = app_eval_dir / "evaluation_report.json"

    if not json_file.exists():
        print(f"❌ Evaluation report not found: {json_file}")
        print("   Run evaluate_all.py first to generate the report.")
        return 1

    # Generate HTML viewer
    output_file = app_eval_dir / "evaluation_viewer.html"
    generate_html_viewer(json_file, output_file)

    print(f"\n🌐 Open in browser: file://{output_file.absolute()}")

    return 0


if __name__ == "__main__":
    exit(main())
