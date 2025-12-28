from dotenv import load_dotenv
import os

load_dotenv()
print("API KEY:", os.getenv("BINGX_API_KEY"))
