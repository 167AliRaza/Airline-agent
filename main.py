from fastapi import FastAPI
from openai import AsyncOpenAI #type: ignore
from openai import OpenAIError #type: ignore
from openai.types.responses import ResponseTextDeltaEvent #type: ignore
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
from agents import Agent, OpenAIChatCompletionsModel, Runner ,function_tool ,TResponseInputItem , set_tracing_disabled#type: ignore
from dotenv import load_dotenv #type: ignore
from pydantic import BaseModel #type: ignore
from typing import Optional
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
import uuid

import os
from db_connection import get_db_client
set_tracing_disabled(disabled=True) # Disable tracing for the agent
load_dotenv()   
app=FastAPI()
class Message(BaseModel):
    message: str

class book_seat_input(BaseModel):
    name: str
    airline_name: str
    seat_number: str
    date: str
    destination: str
    origin: str

    
db_client = get_db_client()
db = db_client["Airline_db"]
# Ensure the API key is set
gemini_api_key = os.getenv('GEMINI_API_KEY')
if not gemini_api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")

client = AsyncOpenAI(
    api_key=gemini_api_key,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
@function_tool
def book_seat(input: book_seat_input)->str:
    """
    Goal:Book a seat on a flight.
    Input:
    - name: str
    - airline_name: str
    - seat_number: str
    - date: str
    - destination: str
    - origin: str
    Output:
    - A message confirming the seat booking along with Ticket Number.
    """
    try:
        ticket_number = str(uuid.uuid4())
        booking_data = input.model_dump()
        booking_data['ticket_number'] = ticket_number        
        db.book_seat.insert_one(booking_data)
        
        return f"Seat {input.seat_number} booked for {input.name} on {input.airline_name} from {input.origin} to {input.destination} on {input.date}. Ticket number: {ticket_number}"

    except Exception as e:
        print(f"Error booking seat: {e}")
        return f"Error booking seat: {e}"


@function_tool
def cancel_seat(ticket_number: str) -> str:
    """
    Goal: Cancel a booked seat.
    Input:
    - ticket_number: str
    Output:
    - A message confirming the cancellation of the seat.
    """
    try:
        result = db.book_seat.delete_one({"ticket_number": ticket_number})
        if result.deleted_count > 0:
            return f"Seat booking with ticket number {ticket_number} has been successfully cancelled."
        else:
            return f"No booking found with ticket number {ticket_number}."
    except Exception as e:
        print(f"Error cancelling seat: {e}")
        return f"Error cancelling seat: {e}"
@function_tool
def update_seat_number(ticket_number: str, new_seat_number: str) -> str:
    """
    Goal: Update the seat number of a booked seat.
    Input:
    - ticket_number: str
    - new_seat_number: str
    Output:
    - A message confirming the update of the seat number and the new seat number.
    """
    try:
        result = db.book_seat.update_one(
            {"ticket_number": ticket_number},
            {"$set": {"seat_number": new_seat_number}}
        )
        if result.modified_count > 0:
            return f"Seat number for ticket {ticket_number} has been updated to {new_seat_number}."
        else:
            return f"No booking found with ticket number {ticket_number} or no change made."
    except Exception as e:
        print(f"Error updating seat number: {e}")
        return f"Error updating seat number: {e}"
@function_tool
def show_booked_seats() -> str:
    """
    Goal: Show all booked seats.
    Input: None
    Output:
    - A list of all booked seats with their details.
    """
    try:
        bookings_cursor = db.book_seat.find()
        bookings = list(bookings_cursor)  # Convert cursor to list once

        if not bookings:  # More efficient and Pythonic
            return "No seats are currently booked."
        
        booked_seats = []
        for booking in bookings:
            booked_seats.append(f"Ticket Number: {booking['ticket_number']}, Name: {booking['name']}, Airline: {booking['airline_name']}, Seat Number: {booking['seat_number']}, Date: {booking['date']}, Origin: {booking['origin']}, Destination: {booking['destination']}")
        return "\n".join(booked_seats)

    except Exception as e:
        print(f"Error showing booked seats: {e}")
        return f"Error showing booked seats: {e}"


@function_tool(
    name_override="faq_lookup_tool", description_override="Lookup frequently asked questions."
)
async def faq_lookup_tool(question: str) -> str:
    if "bag" in question or "baggage" in question:
        return (
            "You are allowed to bring one bag on the plane. "
            "It must be under 50 pounds and 22 inches x 14 inches x 9 inches."
        )
    elif "seats" in question or "plane" in question:
        return (
            "There are 120 seats on the plane. "
            "There are 22 business class seats and 98 economy seats. "
            "Exit rows are rows 4 and 16. "
            "Rows 5-8 are Economy Plus, with extra legroom. "
        )
    elif "wifi" in question:
        return "We have free wifi on the plane, join Airline-Wifi"
    return "I'm sorry, I don't know the answer to that question."

faq_agent = Agent(
    name="FAQ Agent",
    handoff_description="A helpful agent that can answer questions about the airline.",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are an FAQ agent. If you are speaking to a customer, you probably were transferred to from the triage agent.
    Use the following routine to support the customer.
    # Routine
    1. Identify the last question asked by the customer.
    2. Use the faq lookup tool to answer the question. Do not rely on your own knowledge.
    3. If you cannot answer the question, transfer back to the triage agent.""",
    model=OpenAIChatCompletionsModel(model="gemini-2.0-flash", openai_client=client),
    tools=[faq_lookup_tool],
)

     


booking_agent = Agent(
    name="Booking Agent",
    handoff_description="A helpful agent that can Book a seat on a flight, cancel a seat if exist, update a seat number of booked seat and show the booked seats",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    You are a seat booking agent. If you are speaking to a customer, you probably were transferred to from the triage agent.
    Use the following routine to support the customer.
    # Routine if user want to book a seat:
    1. Ask the customer for their Name, Airline Name, desired seat number, date of the flight, origin and destination of the flight
    2. Call the function to Book a seat 
    # Routine if user want to cancel a seat:
    1. Ask for their Ticket Number 
    2. Call the function to Cancel the Seat
    # Routine if user want to update a seat number:
    1. Ask for their Ticket Number and the new seat number
    2. Call the function to Update the Seat Number
    # Routine if user want to show booked seats:
    1. Call the function to Show Booked Seats
    Only If the customer asks a question that is not related to the routine, then transfer back to the triage agent.otherwise deal yourself """,
    model=OpenAIChatCompletionsModel(model="gemini-2.0-flash", openai_client=client),
    tools=[book_seat,cancel_seat,update_seat_number,show_booked_seats],
    
)




triage_agent = Agent(
    name="Triage Agent",
    handoff_description="A triage agent that can delegate a customer's request to the appropriate agent.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX} "
        "You are a helpful triaging agent. You task is to delegate questions to other appropriate agents with the user query without responding to user."
    ),
    model=OpenAIChatCompletionsModel(model="gemini-2.0-flash", openai_client=client),
    handoffs=[
    
        booking_agent,faq_agent,
    ],
)
faq_agent.handoffs.append(triage_agent)
booking_agent.handoffs.append(triage_agent)

history:list[TResponseInputItem]= []



@app.post("/chat")
async def agent_endpoint(message: Message):
    query = message.message
    if not query:
        return {"error": "Query is required"}
    
    history.append({"role": "user", "content": query})
    current_agent = triage_agent

    try:
        result = Runner.run_sync(
         agent,
         query)
        history.append({"role": "assistant", "content": result.final_output})
    
    except Exception as e:
        yield f"[ERROR]: {str(e)}"

    return result.final_output
    



