"""Module: orchestration/dependencies.py

Dependency injection for the VQMS AI pipeline.

Instantiates all pipeline nodes (Steps 7-12), builds the
LangGraph graph, and creates the SQS consumer. Called from
main.py lifespan to wire everything together.
"""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from adapters.graph_api import GraphAPIConnector
from adapters.llm_gateway import LLMGateway
from adapters.salesforce import SalesforceConnector
from adapters.servicenow import ServiceNowConnector
from db.connection import PostgresConnector
from queues.sqs import SQSConnector
from orchestration.sqs_consumer import PipelineConsumer
from orchestration.graph import build_pipeline_graph
from orchestration.nodes.acknowledgment import AcknowledgmentNode
from orchestration.nodes.confidence_check import ConfidenceCheckNode
from orchestration.nodes.context_loading import ContextLoadingNode
from orchestration.nodes.delivery import DeliveryNode
from orchestration.nodes.kb_search import KBSearchNode
from orchestration.nodes.path_decision import PathDecisionNode
from orchestration.nodes.quality_gate import QualityGateNode
from orchestration.nodes.query_analysis import QueryAnalysisNode
from orchestration.nodes.resolution import ResolutionNode
from orchestration.nodes.routing import RoutingNode
from orchestration.prompts.prompt_manager import PromptManager


def create_pipeline(
    settings: Settings,
    postgres: PostgresConnector,
    llm_gateway: LLMGateway,
    salesforce: SalesforceConnector,
    sqs: SQSConnector,
    servicenow: ServiceNowConnector,
    graph_api: GraphAPIConnector,
) -> tuple[Any, PipelineConsumer]:
    """Wire all pipeline components and return the compiled graph + consumer.

    Args:
        settings: Application settings.
        postgres: PostgreSQL connector.
        llm_gateway: Unified LLM gateway (Bedrock primary, OpenAI fallback).
        salesforce: Salesforce connector for vendor lookup.
        sqs: SQS connector for message operations.
        servicenow: ServiceNow connector for ticket operations.
        graph_api: Graph API connector for email operations.

    Returns:
        Tuple of (compiled_graph, pipeline_consumer).
    """
    prompt_manager = PromptManager()

    # Phase 3 nodes (Steps 7-9)
    context_loading = ContextLoadingNode(
        postgres=postgres, salesforce=salesforce, settings=settings,
    )
    query_analysis = QueryAnalysisNode(
        bedrock=llm_gateway, prompt_manager=prompt_manager, settings=settings,
    )
    confidence_check = ConfidenceCheckNode(settings=settings)
    routing = RoutingNode(settings=settings)
    kb_search = KBSearchNode(
        bedrock=llm_gateway, postgres=postgres, settings=settings,
    )
    path_decision = PathDecisionNode(settings=settings)

    # Phase 4 nodes (Steps 10-12)
    resolution = ResolutionNode(
        llm_gateway=llm_gateway, prompt_manager=prompt_manager, settings=settings,
    )
    acknowledgment = AcknowledgmentNode(
        llm_gateway=llm_gateway, prompt_manager=prompt_manager, settings=settings,
    )
    quality_gate = QualityGateNode(settings=settings)
    delivery = DeliveryNode(
        servicenow=servicenow, graph_api=graph_api, settings=settings,
    )

    # Build and compile the graph
    compiled_graph = build_pipeline_graph(
        context_loading_node=context_loading,
        query_analysis_node=query_analysis,
        confidence_check_node=confidence_check,
        routing_node=routing,
        kb_search_node=kb_search,
        path_decision_node=path_decision,
        resolution_node=resolution,
        acknowledgment_node=acknowledgment,
        quality_gate_node=quality_gate,
        delivery_node=delivery,
    )

    # Create consumer
    consumer = PipelineConsumer(
        sqs=sqs,
        compiled_graph=compiled_graph,
        postgres=postgres,
        settings=settings,
    )

    return compiled_graph, consumer
