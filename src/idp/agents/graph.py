
from langgraph.graph import StateGraph, START, END

from idp.agents.state import DocumentState

from idp.agents.classification_agent import ClassificationAgent
from idp.agents.extraction_agent import ExtractionAgent
from idp.agents.validation_agent import ValidationAgent
from idp.agents.anomaly_agent import AnomalyDetectionAgent
from idp.agents.routing_agent import WorkflowRoutingAgent

from idp.llm.provider import GroqProvider
from idp.storage.repository import DocumentRepository
from idp.agents.cross_document_agent import CrossDocumentAgent


def build_agent_graph(repository=None, llm=None):

    # =============================================
    # INITIALIZE AI MODEL PROVIDER
    # =============================================

    llm = llm if llm is not None else GroqProvider()
    repository = repository if repository is not None else DocumentRepository()
    verification_agent = CrossDocumentAgent(repository)
    from idp.policy.service import PolicyService
    policy = PolicyService(repository)
    def bind_policy(state):
        try:
            version = state.get('policy_version_id')
            if version is None:
                version = policy.active()['id']
            return policy.bind(state, version)
        except Exception:
            from idp.policy.schema import DEFAULT
            return {'policy_config': DEFAULT, 'policy_evaluation_error': 'Policy binding failed; manual review required.'}

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
        lambda state: {**extraction_agent.run(state), **{key:value for key,value in bind_policy(state).items() if key.startswith('policy_')}},
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

    graph.add_node("cross_document_verification", verification_agent.run)
    graph.add_edge("anomaly_agent", "cross_document_verification")
    graph.add_node('business_policy', policy.evaluate)
    graph.add_edge("cross_document_verification", 'business_policy')
    graph.add_edge('business_policy', "routing_agent")

    graph.add_edge(
        "routing_agent",
        END,
    )

    return graph.compile()
