from pathlib import Path

from veridex.agent.graph import build_agent_graph


def main():
    graph = build_agent_graph()

    output_path = Path("docs/agent_graph.mmd")
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    mermaid = graph.get_graph().draw_mermaid()
    output_path.write_text(
        mermaid,
        encoding="utf-8",
    )

    print(f"Saved Mermaid graph: {output_path}")


if __name__ == "__main__":
    main()
