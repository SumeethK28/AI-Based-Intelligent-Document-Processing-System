
from langgraph.graph import StateGraph, START, END

from idp.agents.state import DocumentState

from idp.agents.classification_agent import ClassificationAgent
from idp.agents.extraction_agent import ExtractionAgent
from idp.agents.validation_agent import ValidationAgent
from idp.agents.anomaly_agent import AnomalyDetectionAgent
from idp.agents.routing_agent import WorkflowRoutingAgent

from idp.llm.provider import GroqProvider


def build_agent_graph():

    # =============================================
    # INITIALIZE AI MODEL PROVIDER
    # =============================================

    llm = GroqProvider()

    # =============================================
    # INITIALIZE SPECIALIZED AGENTS
    # =============================================

    classification_agent = ClassificationAgent(llm)

    extraction_agent = ExtractionAgent(llm)

    validation_agent = ValidationAgent()

    anomaly_agent = AnomalyDetectionAgent()

    routing_agent = WorkflowRoutingAgent()

    # =============================================
    # BUILD SHARED-STATE GRAPH
    # =============================================

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

    graph.add_node(
        "anomaly_agent",
        anomaly_agent.run,
    )

    graph.add_node(
        "routing_agent",
        routing_agent.run,
    )

    # =============================================
    # GRAPH CONNECTIONS
    # =============================================

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
        "anomaly_agent",
    )

    graph.add_edge(
        "anomaly_agent",
        "routing_agent",
    )

    graph.add_edge(
        "routing_agent",
        END,
    )

    return graph.compile()
