
from langgraph.graph import StateGraph, START, END

from idp.agents.state import DocumentState
from idp.agents.classification_agent import ClassificationAgent
from idp.agents.extraction_agent import ExtractionAgent
from idp.agents.validation_agent import ValidationAgent
from idp.llm.provider import GroqProvider


def build_agent_graph():

    llm = GroqProvider()

    classification_agent = ClassificationAgent(llm)
    extraction_agent = ExtractionAgent(llm)
    validation_agent = ValidationAgent()

    graph = StateGraph(DocumentState)

    graph.add_node(
        "classification_agent",
        classification_agent.run,
    )

    graph.add_node(
        "extraction_agent",
        extraction_agent.run,
    )

    graph.add_node(
        "validation_agent",
        validation_agent.run,
    )

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
        "validation_agent",
    )

    graph.add_edge(
        "validation_agent",
        END,
    )

    return graph.compile()
