import math
from flask import Flask, jsonify,  request
import time
from preprocess_helyos_context import pre_process_map_objects, get_neareset_trailer 
from openai import OpenAI
import json


app = Flask(__name__)


def load_system_message(filepath='./llm_directives/system_message.md'):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

default_system_message = load_system_message()


@app.route("/health")
def health():
    return jsonify(
        status = "UP"
    )  

# Initialize OpenAI client
client = OpenAI(api_key="your-api-key")


def call_gpt_model(question_to_GPT, max_retries=3, retry_delay=2):
    system_message = question_to_GPT.get('system_message', '')
    user_prompt = question_to_GPT.get('prompt', '')
    operation = question_to_GPT.get('operation', '')
    yard_global_state = question_to_GPT.get('yard_global_state', {})

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Operation: {operation}\nYard state: {yard_global_state}\nPrompt: {user_prompt}"}
    ]

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                temperature=0.2,
                max_tokens=1500,
                n=1
            )

            reply_content = response.choices[0].message.content.strip()

            # Attempt to parse the reply
            parsed_response = json.loads(reply_content)
            parsed_response['prompt'] = user_prompt
            return parsed_response

        except json.JSONDecodeError as json_err:
            print(f"[Attempt {attempt+1}] Invalid JSON from GPT. Retrying... Error: {json_err}")
            time.sleep(retry_delay)

        except Exception as e:
            print(f"[Attempt {attempt+1}] Error calling GPT model: {e}")
            time.sleep(retry_delay)

    # After max retries, fail gracefully
    return {"error": "Failed to get a valid JSON response from GPT after multiple attempts."}






@app.post("/plan_job/")
def main():
    """
    This service 

    """
    # Regular helyOS Input data
    request_body = request.get_json() 
    request_data = request_body['request']
    context = request_body['context']
    config = request_body.get('config', {})
    step = context['orchestration']['current_step']

    # GPT-specific input data
    operation = request_data['operation'] # createQuest | repairQuest | evaluateQuest
    quest_id = request_data.get('quest_id', None)
    user_prompt = request_data.get('prompt', None)
    system_message = config.get('system_message', default_system_message) # This is the system message for the GPT model

    # Filter relevant data from helyos context
    helyos_agents = context['agents']
    helyos_agents = [ {  'uuid': agent['uuid'],
                         'name': agent['name'],
                         'x': agent['x'],
                         'y': agent['y'],
                         'z': agent['z'],   
                         'orientations': agent['orientations'],
                         'status': agent['status'],
                         'agent_class': agent['agent_class'],
                         'agent_type': agent['agent_type'],
                         'follower_connections': agent['follower_connections']
                         } for agent in helyos_agents]

    trucks = [agent for agent in helyos_agents if agent['agent_type'] == 'truck']
    trailers = [agent for agent in helyos_agents if agent['agent_type'] == 'trailer']

    map_objects = context['map'].get('map_objects', [])
    targets =  pre_process_map_objects(map_objects, trucks, trailers)

    # Create the GPT context
    yard_global_state = {
        'trucks': trucks,
        'trailers': trailers,
        'targets': targets,
        'current_time': time.time()
    }

    # Error handling  
    if operation == "repairQuest" and quest_id is None:
        raise ValueError('quest_id must be provided')


    if operation == "createQuest":
        question_to_GPT = {
            'system_message': system_message,	
            'prompt': user_prompt,
            'operation': operation,
            'yard_global_state': yard_global_state
        }         

        #Call the GPT model to get the quest
        response = call_gpt_model(question_to_GPT) # This function should be implemented to call the GPT model
        
        quest_operation = response['operation']
        questline_id = response.get('questline_id', None)
        mission_requests = response.get('mission_requests', [])
        repaired_mission_id = response.get('repaired_mission_id', None)
        user_response = response.get('user_response', None)
         
        quest_assignment = {
            'agent_uuid': "gpt-assistant",
            'assignment': {
                'quest_id': quest_id,
                'questline_id': questline_id,
                'mission_requests': mission_requests,
                'repaired_mission_id': repaired_mission_id,
                'user_response': user_response,
                'prompt': user_prompt
            }

         }


        response =  { 'status': "ready",
                      'results': [quest_assignment]                        
                    }
    

    return jsonify(response)





if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9200, debug=True)


