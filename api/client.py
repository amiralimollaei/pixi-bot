import logging
import re
import os
import json

from openai import OpenAI

from .chatting import FunctionCall, Role, RoleMessage

from .utils import exists

# constatnts

MAX_LENGTH = 32000 # the maximum lenght of the conversation in tokens (Approx.), before it get's cut off for cost savings

API_ENDPOINT = "https://api.deepinfra.com/v1/openai"

THINK_PATTERN = re.compile(r"[`\s]*[\[\<]*think[\>\]]*([\s\S]*?)[\[\<]*\/think[\>\]]*[`\s]*")

# models: google/gemini-2.5-pro, deepseek-ai/DeepSeek-R1, deepseek-ai/DeepSeek-V3, meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8, meta-llama/Meta-Llama-3.1-405B-Instruct

class ChatClient:
    def __init__(self, messages: list[RoleMessage] = None, model: str = "google/gemini-2.5-pro"):
        if messages is not None:
            assert isinstance(messages, list), f"expected messages to be of type `list[RoleMessage]` or be None, but got `{messages}`"
            assert all([isinstance(m, RoleMessage) for m in messages]), f"expected messages to be of type `list[RoleMessage]` or be None, but at least one element in the list is not of type `RoleMessage`, got `{messages}`"

        self.model = model
        self.messages = messages or []
        self.session = OpenAI(api_key = os.environ["DEEPINFRA_API_KEY"], base_url = API_ENDPOINT)
        self.system_prompt = None
        self.tools: dict = {}
        self.tool_schema: list[dict] = []

    def register_tool(self, name: str, func, parameters: dict = None, description: str = None):
        """
        Register a tool (function) for tool calling.
        name: tool name (string)
        func: callable
        parameters: OpenAI tool/function parameters schema (dict)
        description: description of the tool (string)
        """
        self.tools[name] = func
        self.tool_schema.append(dict(
            type = "function",
            function = dict(
                name = name,
                description = description or name,
                parameters = parameters or dict(),
            )
        ))

    def set_system(self, prompt: str):
        assert prompt is not None and prompt != ""
        self.system_prompt = prompt
    
    def add_message(self, message: RoleMessage | str):
        assert message is not None
        if isinstance(message, RoleMessage):
            self.messages.append(message)
        elif isinstance(message, str):
            role = None
            match self.messages[-1].role:
                case Role.SYSTEM:
                    role = Role.ASSISTANT
                case Role.ASSISTANT:
                    role = Role.USER
                case Role.USER:
                    role = Role.ASSISTANT
                case _:
                    role = Role.ASSISTANT
            self.messages.append(RoleMessage(role, message))
        else:
            raise ValueError(f"expected message to be a RoleMessage or a string, but got {message}.")
    
    def create_chat_completion(self, stream: bool = False):
        # If tools are registered, add them to the request
        openai_messages = self.get_openai_messages_dict()
        kwargs = dict(
            model = self.model,
            messages = openai_messages,
            temperature = 0.3,
            max_tokens = MAX_LENGTH,
            top_p = 0.5,
            stream = stream,
        )
        if self.tool_schema:
            kwargs["tools"] = self.tool_schema
        return self.session.chat.completions.create(**kwargs)
    
    def get_tool_results(self, tool_calls: list):
        """
        Execute tool calls and return results
        """
        
        function_calls: list[FunctionCall] = []
        for tool_call in tool_calls:
            function = tool_call.function
            function_name = function.name
            function_arguments = json.loads(function.arguments)
            index = tool_call.index
            id = tool_call.id
            function_calls.append(FunctionCall(
                name=function_name,
                arguments=function_arguments,
                index=index,
                id=id
            ))
        
        results = [RoleMessage(
            Role.ASSISTANT,
            content = None,
            tool_calls = function_calls
        )]
        for fn in function_calls:
            func = self.tools.get(fn.name)
            if func:
                try:
                    result = func(**fn.arguments)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Tool '{fn.name}' not found."
            results.append(RoleMessage(
                Role.TOOL,
                content = str(result),
                tool_call_id = fn.id,
            ))
        return results

    def stream_request(self):
        response = ""
        finish_reason = None
        for event in self.create_chat_completion(stream=True):
            if event.choices is None or len(event.choices) == 0:
                continue
            choice = event.choices[0]
            if exists(_tool_calls := choice.delta.tool_calls):
                # append the assistant's response
                if response:
                    self.messages.append(RoleMessage(
                        Role.ASSISTANT,
                        content=response,
                    ))
                self.messages += self.get_tool_results(_tool_calls)
                # Recursively call stream_request and yield its results, then return immediately
                yield from self.stream_request()
                return
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            if content := choice.delta.content:
                response += content
                # now yields the response character by character for easier parsing
                for char in content:
                    yield char
        logging.debug(f"finish reason: {finish_reason}")
        
    def request(self) -> str:
        choice = self.create_chat_completion(stream=False).choices[0]
        if choice.message.content:
            return choice.message.content

        # if tools are called, reslove them and repeat the request recursively
        if tool_calls:= choice.message.tool_calls:
            self.messages += self.get_tool_results(tool_calls)
            return self.request()

    def get_openai_messages_dict(self) -> list[dict]:
        messages = self.messages.copy()
        
        final_len = 0
        for idx, message in enumerate(messages):
            role = message.role
            context = message.content or ""
            final_len += len(role) + len(context) + 3
            if final_len > MAX_LENGTH * 4:
                break

        if len(messages) != (idx + 1):
            print("WARN: unable to fit all messages in one request.")
            messages = messages[-idx:]

        openai_messages = [msg.to_openai_dict() for msg in messages]
        # add system as the last message to ensure it is in the model's context
        if exists(self.system_prompt):
            openai_messages.append(RoleMessage(Role.SYSTEM, self.system_prompt).to_openai_dict())
        return openai_messages

    def stream_ask(self, message: str | RoleMessage, temporal: bool = False):
        if temporal:
            orig_messages = self.messages.copy()
        
        if isinstance(message, str):
            message = RoleMessage(Role.USER, message)
        else:
            assert isinstance(message, RoleMessage), "Message must be a string or a RoleMessage."
        assert message.role == Role.USER, "Message must be from the user."
        self.messages.append(message)
        
        start_think_match = re.compile(r"[\[\<]t?h?i?n?k?[\>\]]?")
        whitespace_match = re.compile(r"\s*")

        response: str = ""
        is_thinking = False
        for chunk in self.stream_request():
            response += chunk

            if start_think_match.match(response):
                is_thinking = True
            else:
                if not whitespace_match.match(response):
                    is_thinking = False

            if is_thinking and THINK_PATTERN.match(response):
                response = THINK_PATTERN.sub("", response)
            
            if not is_thinking:
                yield chunk

        if temporal:
            self.messages = orig_messages
        
    def ask(self, message: str | RoleMessage, temporal: bool = False):
        if temporal:
            orig_messages = self.messages.copy()
            
        if isinstance(message, str):
            message = RoleMessage(Role.USER, message)
        else:
            assert isinstance(message, RoleMessage), "Message must be a string or a RoleMessage."
        assert message.role == Role.USER, "Message must be from the user."
        self.messages.append(message)

        response = THINK_PATTERN.sub("", self.request())
        
        if temporal:
            self.messages = orig_messages
        return response

    def to_dict(self):
        return dict(
            system_prompt = self.system_prompt,
            messages = [msg.to_dict() for msg in self.messages]
        )

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            messages = [RoleMessage.from_dict(msg) for msg in data.get("messages") or []],
            system_prompt = data.get("system_prompt"),
        )

if __name__ == "__main__":
    # Example dummy function hard coded to return the same weather
    # In production, this could be your backend API or an external API
    def get_current_weather(location):
        """Get the current weather in a given location"""
        print("Calling get_current_weather client side.")
        return 75
        
    chat = ChatClient()
    chat.register_tool(
        name = "get_current_weather",
        func = get_current_weather,
        parameters = dict(
            type = "object",
            properties = {
                "location": {
                    "type": "string",
                    "description": "The location to get the weather for. (Required)",
                }
            },
            required = [
                "location"
            ],
            additionalProperties = False
        ),
        description = "Get the current weather in a given location."
    )
    
    while True:
        query = input("You: ")
        print("LLM: ", end="")
        response = ""
        for resp in chat.stream_ask(query):
            response += resp
            print(resp, end="", flush=True)
        print()
        #chat.add_message(response)