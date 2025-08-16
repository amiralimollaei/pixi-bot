from dataclasses import dataclass, asdict
import asyncio
import json
import logging
import math
import os
import time
import random
from inspect import Parameter, signature

from flask import Flask, request, jsonify

from .typing import AsyncPredicate, Optional
from .chatbot import AsyncChatbotInstance, CachedAsyncChatbotFactory
from .agents import AgentBase, RetrievalAgent
from .apis import AsyncGiphyAPI, AsyncWikimediaAPI
from .chatbot import AssistantPersona, PredicateCommand, PredicateTool
from .chatting import ChatMessage
from .database import DirectoryDatabase
from .enums import ChatRole, Messages, Platform
from .reflection import ReflectionAPI
from .addon import AddonManager

@dataclass
class APIResponse:
    success: bool
    error: str = None
    data: dict = None

    def to_dict(self):
        return jsonify(asdict(self))

# constants

COMMAND_PREFIXES = ["!pixi", "!pix", "!p"]


# helper functions

def remove_prefixes(text: str):
    for prefix in COMMAND_PREFIXES:
        text = text.removeprefix(prefix)
    return text


class FlaskServer(Flask):
    def __init__(self,
        *,
        model: str,
        helper_model: str,
        api_url: str,
        persona_file: str = "persona.json",
        database_names: Optional[list[str]] = None,
        enable_tool_calls: bool = False,
        log_tool_calls: bool = False,
        **flask_kwargs
    ):
        super().__init__("PixiFlaskServer", **flask_kwargs)

        self.persona = AssistantPersona.from_json(persona_file)

        self.api_url = api_url
        self.chatbot_factory = CachedAsyncChatbotFactory(
            parent=self,
            model=model,
            base_url=api_url,
            persona=self.persona,
            hash_prefix="FlaskServer",
            log_tool_calls=log_tool_calls,
        )

        self.helper_model = helper_model
        self.enable_tool_calls = enable_tool_calls

        self.database_names = database_names or []
        self.database_tools_initalized = asyncio.Event()

        try:
            self.giphy_api = AsyncGiphyAPI()
        except KeyError:
            logging.warning("GIPHY_API_KEY is not set, GIF features will not be available.")
            self.giphy_api = None

        # TODO: add configurable wikis
        if self.enable_tool_calls:
            self.init_mediawiki_tools(url="https://minecraft.wiki/", wiki_name="minecraft")
            self.init_mediawiki_tools(url="https://www.wikipedia.org/w/", wiki_name="wikipedia")
            # self.init_mediawiki_tools(url="https://mcdf.wiki.gg/", wiki_name="minecraft_discontinued_features")

        #self.addon_manager = AddonManager(self)
        #self.addon_manager.load_addons()
        
        self.__register_instance_apis()

    def __register_instance_apis(self):
        async def get_instance(instance_id: str):
            if instance_id is None:
                return APIResponse(
                    success=False,
                    error="instance_id is required"
                ).to_dict(), 400
            instance = await self.chatbot_factory.get(instance_id)
            if instance is None:
                return APIResponse(
                    success=False,
                    error="instance not found"
                ).to_dict(), 404
            return APIResponse(
                success=True,
                data=instance.to_dict()
            ).to_dict(), 200

        self.__register_api("instance/get", get_instance, method="GET")
        
        async def get_or_create_instance(instance_id: str):
            if instance_id is None:
                return APIResponse(
                    success=False,
                    error="instance_id is required"
                ).to_dict(), 400
            instance = await self.chatbot_factory.get_or_create(instance_id)
            assert instance is not None
            return APIResponse(
                success=True,
                data=instance.to_dict()
            ).to_dict(), 200

        self.__register_api("instance/get_or_create", get_or_create_instance, method="GET")
        
        async def remove_instance(instance_id: str):
            if instance_id is None:
                return APIResponse(
                    success=False,
                    error="instance_id is required"
                ).to_dict(), 400
            self.chatbot_factory.remove(instance_id)
            return APIResponse(
                success=True,
            ).to_dict(), 200

        self.__register_api("instance/remove", remove_instance, method="DELETE")
        
        async def add_message_instance(instance_id: str, message: str):
            if instance_id is None:
                return APIResponse(
                    success=False,
                    error="instance_id is required"
                ).to_dict(), 400
            instance = await self.chatbot_factory.get_or_create(instance_id)
            chatmessage: ChatMessage = instance.add_message(message)
            instance.save()
            return APIResponse(
                success=True,
                data=chatmessage.to_dict()
            ).to_dict(), 200

        self.__register_api("instance/add_message", add_message_instance, method="POST")
        
        async def request_response_instance(instance_id: str):
            if instance_id is None:
                return APIResponse(
                    success=False,
                    error="instance_id is required"
                ).to_dict(), 400
            instance = await self.chatbot_factory.get_or_create(instance_id)
            assert instance is not None
            return APIResponse(
                success=True,
                data=await instance.client.request()
            ).to_dict(), 200

        self.__register_api("instance/request_response", request_response_instance, method="GET")
    
    async def __init_database_tools(self):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a database tool, but tool calls are disabled")
            self.database_tools_initalized.set()
            return

        await asyncio.gather(*(
            self.init_database_tool(database_name) for database_name in self.database_names
        ))
        self.database_tools_initalized.set()

    async def init_database_tool(self, database_name: str):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a database tool, but tool calls are disabled")
            return

        database_api = await DirectoryDatabase.from_directory(database_name)

        async def get_entry_as_str(entry_id: int):
            dataset_entry = await database_api.get_entry(entry_id)
            return json.dumps(asdict(dataset_entry), ensure_ascii=False)

        async def search_database(instance: AsyncChatbotInstance, reference: ChatMessage, keyword: str):
            return [asdict(match) for match in await database_api.search(keyword)]

        self.register_tool(
            name=f"search_{database_name}_database",
            func=search_database,
            parameters=dict(
                type="object",
                properties=dict(
                    keyword=dict(
                        type="string",
                        description=f"The search keyword to find matches in the database text from the {database_name} database",
                    ),
                ),
                required=["keyword"],
                additionalProperties=False
            ),
            description=f"Searches the {database_name} database based on a keyword and returns the entry metadata. you may use this function multiple times to find the specific information you're looking for."
        )

        async def query_database(instance: AsyncChatbotInstance, reference: ChatMessage, query: str, ids: str):
            if ids is None:
                return "no result: no id specified"

            agent: RetrievalAgent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    get_entry_as_str(int(entry_id.strip())) for entry_id in ids.split(",")
                ])
            )
            return await agent.retrieve(query)

        self.register_tool(
            name=f"query_{database_name}_database",
            func=query_database,
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(
                        type="string",
                        description=f"A question or a statement that you want to find information about.",
                    ),
                    ids=dict(
                        type="string",
                        description=f"Comma-seperated numerical entry ids to fetch and query information from, use `search_{database_name}_database` to optain entry ids based a search term.",
                    ),
                ),
                required=["query", "ids"],
                additionalProperties=False
            ),
            description=f"runs an LLM agent to fetch and query the contents of the {database_name} database using the entry ids for finding relevent entries and a more detailed query for finding relevent information, note that this will not return all the information that the page contains, you might need to use this command multiple times to get all the information out of the database entry."
        )

    def init_mediawiki_tools(self, url: str, wiki_name: str):
        if not self.enable_tool_calls:
            logging.warning("tried to initalize a mediawiki tool, but tool calls are disabled")
            return

        wiki_api = AsyncWikimediaAPI(url)

        async def search_wiki(instance: AsyncChatbotInstance, reference: ChatMessage, keyword: str):
            return [asdict(search_result) for search_result in await wiki_api.search(keyword)]

        self.register_tool(
            name=f"search_wiki_{wiki_name}",
            func=search_wiki,
            parameters=dict(
                type="object",
                properties=dict(
                    keyword=dict(
                        type="string",
                        description=f"The search keyword to find matches in the wiki text from the {wiki_name} wiki",
                    ),
                ),
                required=["keyword"],
                additionalProperties=False
            ),
            description=f"Searches the {wiki_name} wiki based on a keyword. returns the page URL and Title, and optionally the description of the page. you may use this function multiple times to find the specific page you're looking for."
        )

        async def query_wiki_content(instance: AsyncChatbotInstance, reference: ChatMessage, titles: str, query: str):
            if titles.split("|") is None:
                return "no result: no page specified"

            agent: RetrievalAgent = self.create_agent_instance(
                agent=RetrievalAgent,
                context=await asyncio.gather(*[
                    wiki_api.get_raw(t.strip()) for t in titles.split("|")
                ])
            )
            return await agent.retrieve(query)

        self.register_tool(
            name=f"query_wiki_content_{wiki_name}",
            func=query_wiki_content,
            parameters=dict(
                type="object",
                properties=dict(
                    query=dict(
                        type="string",
                        description=f"A question or a statement that you want to find information about.",
                    ),
                    titles=dict(
                        type="string",
                        description=f"Page titles to fetch and query information from, seperated by a delimiter character: `|`. use `search_wiki_{wiki_name}` to optain page titles based a search term.",
                    ),
                ),
                required=["query", "titles"],
                additionalProperties=False
            ),
            description=f"runs an LLM agent to fetch and retrieve relevent information from the contents of the {wiki_name} wiki. \
                This will not return all the information that the page contains, you might need to use this command multiple \
                times to find the information you're looking for."
        )
    
    def register_tool(self, name: str, func, parameters: dict, description: Optional[str], predicate: Optional[AsyncPredicate] = None):
        if not self.enable_tool_calls:
            logging.warning("tried to register a tool, but tool calls are disabled")
            return

        self.chatbot_factory.register_tool(PredicateTool(
            name=name,
            func=func,
            parameters=parameters,
            description=description,
            predicate=predicate
        ))

    def register_command(self, name: str, func, field_name: str, description: str, predicate: Optional[AsyncPredicate] = None):
        self.chatbot_factory.register_command(PredicateCommand(
            name=name,
            func=func,
            field_name=field_name,
            description=description,
            predicate=predicate
        ))

    def __register_api(self, path: str, function, method: str = "GET"):
        func_signature = signature(function)
    
        async def view_func():
            if not request.is_json:
                return APIResponse(success=False, error="request must be a valid json"), 400
            kwargs: dict = request.get_json()
            given_keys = set(kwargs.keys())
            acceptable_keys = set(func_signature.parameters.keys())
            
            #present_keys = given_keys & acceptable_keys
            extra_keys = given_keys - acceptable_keys
            absent_keys = acceptable_keys - given_keys
            required_absent_keys = []
            
            if extra_keys:
                return APIResponse(success=False, error=f"unknown keyword arguments found: {list(extra_keys)}"), 400
            
            if absent_keys:
                for key in list(absent_keys):
                    parameter = func_signature.parameters[key]
                    if parameter.default == Parameter.empty:
                        required_absent_keys.append(key)
            
            if required_absent_keys:
                return APIResponse(success=False, error=f"required keyword argument not specified: {list(required_absent_keys)}"), 400

            try:
                return await function(**kwargs)
            except Exception as e:
                return APIResponse(success=False, error=f"Internal server error: {e}"), 500

        endpoint_name = f"__view_func_{random.randbytes(32).hex()}"
        @self.route(f'/api/{path}', methods=[method], endpoint=endpoint_name)
        async def jsonify_view_func():
            response, status_code = await view_func()
            if isinstance(response, APIResponse):
                response = jsonify(asdict(response))
            return response, status_code