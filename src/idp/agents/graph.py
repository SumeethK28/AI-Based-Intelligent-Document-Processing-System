
from langgraph.graph import StateGraph, START, END

from idp.agents.state import DocumentState
from idp.agents.classification_agent import (
    ClassificationAgent,
)
from idp.agents.extraction_agent import (
    ExtractionAgent,
)
from idp.llm.provider import GroqProvider


def build_agent_graph():

    # Shared Groq client for both agents
    llm = GroqProvider()

    classification_agent = ClassificationAgent(llm)
    extraction_agent = ExtractionAgent(llm)

    graph = StateGraph(DocumentState)

    # Register agent nodes
    graph.add_node(
        "classification_agent",
        classification_agent.run,
    )

    graph.add_node(
        "extraction_agent",
        extraction_agent.run,
    )

    # Define execution order
    graph.add_edge(
        START,
        "classification_agent",
    )

    graph.add_edge(
        "classification_agent",
        "extraction_agent",
    )

    graph.add_edge(
        "extraction_agent",
        END,
    )

    return graph.compile()
