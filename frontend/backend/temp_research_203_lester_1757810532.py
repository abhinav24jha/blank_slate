
import sys
sys.path.append('.')
from deep_research_pipeline import run_open_research

question = "What area needs improvement and what problems do you see?"
user_answer = "kafnasdjfnasdjf"
topic = "community amenity development"
out_prefix = "203_lester_1757810532"
api_provider = "gemini"

print("Starting research pipeline...")
run_open_research(question, user_answer, topic, out_prefix, api_provider)
print("Research pipeline completed!")
