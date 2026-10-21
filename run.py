"""Start the MVP dashboard: python run.py"""
import os
import uvicorn
if __name__=='__main__':
    uvicorn.run('app.main:app',host=os.getenv('SOMAS_HOST','127.0.0.1'),port=int(os.getenv('SOMAS_PORT','8000')),reload=False)
