# app.build (agent)

> # ⚠️ THIS PROJECT IS NO LONGER SUPPORTED
>
> **`appdotbuild-agent` is unmaintained.** It receives **no updates, no fixes, and no support**, and this will not change.
>
> - 🚫 **Not supported** — issues are not monitored or answered.
> - 🚫 **No pull requests** — PRs will **not** be reviewed, accepted, or merged.
> - 🚫 **No updates or releases** — the code is frozen as-is.
> - 🚫 **No security patches** — do not rely on it in production.
>
> The source remains public for **research and reference only**. Fork it and use it entirely **at your own risk** — no warranty, no support channel.

**app.build** is an open-source AI agent for generating production-ready applications with testing, linting and deployment setup from a single prompt. This agent relies heavily on scaffolding and extensive validation to ensure high-quality outputs.

There were two generations of this agent:

### v1 - Python implementation

Original standalone agent located in `./agent/` directory. It was designed to generate CRUD applications on three stacks: (TypeScript + tRPC + Drizzle + React, Python + NiceGUI + SQLModel, PHP + Laravel). The managed service has been discontinued.

See [agent/README.md](agent/README.md) for setup and some usage instructions.

Work report is available on [arXiv](https://arxiv.org/abs/2509.03310) (accepted at [SANER 2026](https://conf.researchr.org/home/saner-2026))

### v2 - Rust implementation 🦀

It is located in `./edda/` directory. The purpose of this version was to build a more robust architecture with a focus on data applications (dashboards, analytics, data-driven tools).

Unlike the Python version, it is available not only as a standalone agent but also as a MCP powering your favorite agents (like Claude Code) or being wrapped into custom agents programmatically (see `klaudbiusz/cli/codegen.py` for the example of using with Claude Agent SDK).

Some tools for bulk app generation and evaluation of this version are available under `klaudbiusz` (wrappers over Claude SDK and relevant orchestration/glue code). 

### MCP Installation

**Prerequisites:**
- OCI-compatible container runtime (Docker, OrbStack, Podman...) must be installed and running for Dagger-based sandboxed execution

```
curl -LsSf https://raw.githubusercontent.com/neondatabase/appdotbuild-agent/refs/heads/main/edda/install.sh | sh
```
and attach to your favorite MCP client, e.g. Claude Code:
```
claude mcp add --transport stdio edda -- ~/.local/bin/edda_mcp
```

**Set Databricks environment variables** (required for app generation):
```bash
export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
export DATABRICKS_TOKEN=dapi...
export DATABRICKS_WAREHOUSE_ID=your-warehouse-id
```

Then start using it with Claude Code:
```bash
# Create project dir
mkdir ~/dbrx-sales-by-region && cd ~/dbrx-sales-by-region

# Check the 'edda' MCP is available fo claude
claude mcp list

# Run sample app generation
claude "Create a Databricks app that shows daily sales by region"
```

**To deploy to Databricks** (optional, requires write to /usr/local/bin), install Databricks CLI:
```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sudo sh
```


## Citation

If you use this work in your research, please cite our paper:

```bibtex
@misc{kniazev2025appbuildproductionframeworkscaling,
      title={app.build: A Production Framework for Scaling Agentic Prompt-to-App Generation with Environment Scaffolding},
      author={Evgenii Kniazev and Arseny Kravchenko and Igor Rekun and James Broadhead and Nikita Shamgunov and Pranav Sah and Pratik Nichite and Ivan Yamshchikov},
      year={2025},
      eprint={2509.03310},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2509.03310}
}
```

---
Supported by Neon and Databricks.

Built to showcase agent-native infrastructure patterns. Fork it, remix it, use it as a reference for your own projects.
