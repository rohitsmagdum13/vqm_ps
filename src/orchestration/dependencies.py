"""Module: orchestration/dependencies.py

Dependency injection for the VQMS AI pipeline.

Instantiates all pipeline nodes, builds the LangGraph graph,
and creates the SQS consumer. Called from main.py lifespan
to wire everything together.
"""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from adapters.llm_gateway import LLMGateway
from db.connection import PostgresConnector
from adapters.salesforce import SalesforceConnector
from queues.sqs import SQSConnector
from orchestration.sqs_consumer import PipelineConsumer
from orchestration.graph import build_pipeline_graph
from orchestration.nodes.confidence_check import ConfidenceCheckNode
from orchestration.nodes.context_loading import ContextLoadingNode
from orchestration.nodes.kb_search import KBSearchNode
from orchestration.nodes.path_decision import PathDecisionNode
from orchestration.nodes.query_analysis import QueryAnalysisNode
from orchestration.nodes.routing import RoutingNode
from orchestration.prompts.prompt_manager import PromptManager


def create_pipeline(
    settings: Settings,
    postgres: PostgresConnector,
    llm_gateway: LLMGateway,
    salesforce: SalesforceConnector,
    sqs: SQSConnector,
) -> tuple[Any, PipelineConsumer]:
    """Wire all pipeline components and return the compiled graph + consumer.

    Args:
        settings: Application settings.
        postgres: PostgreSQL connector.
        llm_gateway: Unified LLM gateway (Bedrock primary, OpenAI fallback).
        salesforce: Salesforce connector for vendor lookup.
        sqs: SQS connector for message operations.

    Returns:
        Tuple of (compiled_graph, pipeline_consumer).
    """
    prompt_manager = PromptManager()

    # Instantiate all pipeline nodes
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

    # Build and compile the graph
    compiled_graph = build_pipeline_graph(
        context_loading_node=context_loading,
        query_analysis_node=query_analysis,
        confidence_check_node=confidence_check,
        routing_node=routing,
        kb_search_node=kb_search,
        path_decision_node=path_decision,
    )

    # Create consumer
    consumer = PipelineConsumer(
        sqs=sqs,
        compiled_graph=compiled_graph,
        postgres=postgres,
        settings=settings,
    )

    return compiled_graph, consumer
