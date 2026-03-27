import os
import requests
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from dataclasses import dataclass
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel, Field
from langchain.tools import tool
import uuid


@tool('fetch_weather', description="Get the weather for a given city from wttr.in. Input should be plain city name.", return_direct=True)
def fetch_weather(city: str) -> str:
    """Fetch raw weather data from wttr.in and return short human summary."""
    if not city:
        return "City is required."

    url = f"http://wttr.in/{city}?format=j1"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    current = data.get("current_condition", [{}])[0]
    weather = data.get("weather", [])

    temp_c = current.get("temp_C", "N/A")
    feels_like_c = current.get("FeelsLikeC", "N/A")
    condition = current.get("weatherDesc", [{}])[0].get("value", "N/A")
    humidity = current.get("humidity", "N/A")
    wind_kph = current.get("windspeedKmph", "N/A")

    forecast = []
    for day in weather[:3]:
        date = day.get("date", "N/A")
        max_temp = day.get("maxtempC", "N/A")
        min_temp = day.get("mintempC", "N/A")
        desc = day.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value", "N/A")
        forecast.append(f"{date}: {desc}, {min_temp}C..{max_temp}C")

    forecast_str = "\n".join(forecast) if forecast else "No forecast available."

    return (
        f"Weather for {city}:\n"
        f"Current: {condition}, {temp_c}C (feels like {feels_like_c}C), humidity {humidity}%, wind {wind_kph} km/h.\n"
        f"3-day forecast:\n{forecast_str}"
    )

# @dataclass
# class ResponseFormat:
#     """Define the expected response format for the agent."""
#     summary: str
#     temperature: float
#     humidity: float
#     wind_speed: float
#     forecast: str


class ResponseFormat(BaseModel):
    summary: str = Field(description="Friendly summary of the weather")
    temperature: float = Field(description="Temp in Celsius")
    humidity: float
    wind_speed: float
    forecast: str


checkpointer = InMemorySaver()

config = {'configurable': {'thread_id':str(uuid.uuid4())}}


def create_weather_agent() -> object:
    """Construct a LangChain agent with Gemini 2.5 flash and wttr.in tool."""
    load_dotenv()

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        raise ValueError("Please set GOOGLE_API_KEY or GENAI_API_KEY in .env")

    llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    thinking_budget = 1024,
    include_thoughts=True,
    temperature=0.7,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)
    agent = create_agent(
        model=llm,
        tools=[fetch_weather],
        system_prompt="You are a helpful weather assistant that explains steps explicitly.",
        response_format=ResponseFormat,
        checkpointer=checkpointer,
    )

    return agent


def main():
    agent = create_weather_agent()

    city = input("Enter city for weather report: ").strip()
    if not city:
        print("No city provided, exiting.")
        return

    # # prompt = "Analyze the user's location request, determine the best way to use the weather tool, and then provide a structured report. Think step-by-step before acting. List out your thinking process"
    # prompt = f"Use weather_lookup to fetch weather for {city} and summarize in friendly language."
    # result = agent.invoke({"messages": [
    #                                     {'role':'user',
    #                                     'content': prompt
    #                                 }
    #                                 ]},
    #                         config = config)       
    prompt = (
    f"You are a reasoning weather assistant. "
    f"First explain your plan and which tool you will call. "
    f"Then call fetch_weather for city {city} and finally summarize the result.\n\n"
    f"City: {city}\n"
    f"Steps:\n"
    f"1) Determine if weather data is needed.\n"
    f"2) Use fetch_weather with city.\n"
    f"3) Report exactly what you got and conclude.\n"
)

    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config=config)
    print("\n=== Gemini's Thinking Process ===")
    for chunk in agent.stream(
        {"messages":[{"role":"user","content":prompt}]},
        config=config,
        stream_mode="updates",
    ):
        print(chunk)
    for msg in result["messages"]:
        # 1. Check for 'thought' in the metadata
        thought = msg.additional_kwargs.get("thought")
        if thought:
            print(f"💭 {thought}")
        
        # 2. Check for the actual tool decision
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            print(f"🛠️ Decision: Calling {msg.tool_calls[0]['name']} for {city}")                                                        

    print("\n=== Final Structured Response ===")
    print("\n=== Weather Agent Response ===")
    # Agent invoke returns a dict with messages; final output is usually in the last message.
    # if isinstance(result, dict) and "messages" in result:
    #     messages = result["messages"]
    #     if messages:
    #         print(messages[-1].content)
    #         return
    # This is the line that fixes 'None'
    weather_data = result.get("structured_response")

    if weather_data:
        print(f'Structured Response not None: {weather_data}')
        print(f"Summary: {weather_data.summary}")
        print(f"Temperature: {weather_data.temperature}°C")
        print(f"Forecast: {weather_data.forecast}")
    else:
        # If the model failed to trigger the structured node, check the last message
        print("Raw Message:", result["messages"][-1].content)
    
    result = agent.invoke({"messages": [{"role": "user", "content": 'And is this usual?'}]}, config=config)
    print(result["messages"][-1].content)

if __name__ == "__main__":
    main()
