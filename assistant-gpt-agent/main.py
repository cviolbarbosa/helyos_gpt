from helyos_agent_sdk import HelyOSClient, MissionRPCConnector, AgentConnector, DatabaseConnector
from helyos_agent_sdk.models import AssignmentCurrentStatus, ASSIGNMENT_STATUS
from helyos_agent_sdk.utils import replicate_helyos_client
from database_interface import MongoDBConnector, MANAGED_STATUS, MISSION_STATUS, QUEST_STATUS
from interface_ops import update_questline_status, dispatch_mission_to_helyos, pool_and_update_mission_status

import os, threading
import time
from enum import Enum
import uuid

# Load environment variables (optional: use dotenv in dev environments)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "helyosQuestline")

RBMQ_HOST = os.getenv("HELYOS_HOST", "local_message_broker")
UUID = os.getenv("UUID", "gpt-assistant")
AGENT_PASS = os.getenv("HELYOS_PASS", "secret_password")
YARD_UID = os.getenv("YARD_UID", "EM01")
FAILURE_LIMIT = 1


# Connect Mongo DB.
mongodb_connector = MongoDBConnector(uri=MONGO_URI, db_name=MONGO_DB_NAME)
mongodb_connector.delete_all_missions()


# Connect to helyOS using AMQP.
UUID = "gpt-assistant"
print(f"Connecting to HelyOS Core at {RBMQ_HOST} as {UUID}...")
helyos_client = HelyOSClient(RBMQ_HOST, uuid=UUID)
helyos_client.yard_uid = YARD_UID
helyos_client.connect(username=UUID, password=AGENT_PASS)
agent_connector = AgentConnector(helyos_client)
agent_connector.publish_state(status='free', assignment_status= None)


# Create another channel for the mission watcher thread
helyos_client_for_mission_thread = replicate_helyos_client(helyos_client)
helyos_client_for_mission_thread.yard_uid = 'EM01'
helyos_client_for_mission_thread.connect(username=UUID, password=AGENT_PASS)
mission_rpc = MissionRPCConnector(helyos_client_for_mission_thread)
agent_connector_for_mission_thread = AgentConnector(helyos_client_for_mission_thread)

# Create another channel for the database request 
helyos_client_for_db_thread = replicate_helyos_client(helyos_client)
helyos_client_for_db_thread.yard_uid = 'EM01'
helyos_client_for_db_thread.connect(username=UUID, password=AGENT_PASS)
db_rpc = DatabaseConnector(helyos_client_for_db_thread)



def register_questline_and_create_child_missions(ch, sender, assignment, msg_str, signature):
    """
    This function is called when an assignment is received from HelyOS Core and save them as a questline in MongoDB.
    It also creates child missions based on the questline data and dispatches. These missions will be later dispatched to helyOS.
    """
    print(" => assignment is received")
    assignment_metadata = assignment.metadata
    # The assignment body contains the data for the questline and child missions as generated by the LLM.
    prompt =    assignment.body.get('prompt', '')
    operation =    assignment.body.get('operation', 'create_quest')
    questline_id = assignment.body.get('questline_id', None)
    mission_requests =   assignment.body.get('mission_requests', [])
    repaired_mission_id =   assignment.body.get('repaired_mission_id', None)
    
    print(f"Assignment ID: {assignment_metadata.id}, Status: {assignment_metadata.status}, WProcess: {assignment_metadata.work_process_id}")

    try:
        if operation == 'create_quest':
            questline = mongodb_connector.create_questline(
                                prompt = prompt,
                                assignment_id = assignment_metadata.id,
                                mission_id = assignment_metadata.work_process_id,
                                data = mission_requests,
                                assignment_status = ASSIGNMENT_STATUS.ACTIVE,
                                quest_state = QUEST_STATUS.CREATING)
            print(f"Questline created {questline['_id']} using assignment {assignment_metadata.id}")

        if operation == 'update_quest':
            mongodb_connector.delete_waiting_child_missions(questline_id)
            questline = { '_id': questline_id, 'data': mission_requests, 'managed_status': QUEST_STATUS.UPDATING}

        if operation == 'failing_quest': # assistant gives up fixing the quest
            mongodb_connector.update_child_mission(repaired_mission_id, managed_status=MANAGED_STATUS.FAILED)
            pass
    
        # The questlien data is the request data for the children as generated by the LLM.
        for mission_request in mission_requests:
            mongodb_connector.create_child_mission(
                                            id='undefined', status=MANAGED_STATUS.WAITING,
                                            parent_quest_id = questline['_id'], 
                                            data = mission_request['data'], # json data for the mission                                            
                                            order = mission_request['order'], # used to sort the missions in the questline
                                            agent_uuids = mission_request['agent_uuids'],
                                            work_process_type_name = mission_request['work_process_type_name']
                                            )


        if repaired_mission_id:
            mongodb_connector.update_child_mission(repaired_mission_id, managed_status=MANAGED_STATUS.CHECKED)

        # The assistant is not blocked while executing the questline. So its status will be "free"
        update_questline_status(mongodb_connector, agent_connector, questline['_id'], assignment_status=ASSIGNMENT_STATUS.EXECUTING, managed_status=QUEST_STATUS.EXECUTING )
        
   
    except Exception as Err:
        agent_connector.publish_state( status='free', 
                                       assignment_status=AssignmentCurrentStatus(id=assignment_metadata.id, 
                                                                                status=ASSIGNMENT_STATUS.FAILED, 
                                                                                result={},
                                                                                )
        )
        raise Err
        


def dispatch_next_ready_child_mission():
    """
    Dispatch the next ready child mission to HelyOS.
    This function iterates through all waiting child missions obtained via the MongoDB connector. For each mission:
        - If the mission's order is 1, it is dispatched immediately.
        - If the mission's order is greater than 1, the function checks whether all preceding missions have been processed with a status of MANAGED_STATUS.CHECKED.
          Only if all previous missions meet this condition, the current mission is dispatched.
    Dispatching is performed by calling the dispatch_mission_to_helyos function.
    """

    # Check for the waiting missions and request them to HelyOS
    for waiting_mission in mongodb_connector.search_child_waiting_missions():
        parent_quest_id = waiting_mission['parentQuestId']
        order = waiting_mission['order']

        if order == 1:
            dispatch_mission_to_helyos(waiting_mission,  mission_rpc, mongodb_connector)
        else:
            # Check if all the previous missions are completed
            previous_missions = list(mongodb_connector.search_child_missions(parent_quest_id, order - 1))
            if previous_missions:
                for mission in previous_missions:
                    if mission['assistantManagedStatus'] != MANAGED_STATUS.CHECKED:
                        break
                else:
                    dispatch_mission_to_helyos(waiting_mission,  mission_rpc, mongodb_connector)



def child_missions_watcher(helyos_client):
    """
    This function runs in a separate thread and continuously checks for child missions that are not yet checked.
    It retrieves the list of unchecked missions from the MongoDB connector.
    After that, it calls the dispatch_next_ready_child_mission function to dispatch any ready child missions.
    It also checks the status of executing missions and updates their status in the MongoDB database.
    If a mission is completed successfully, it marks it as checked and updates the questline status.
    If a mission fails, it registers the failure in the questline and asks for help from the AI.
    If the failure limit is reached, it marks the quest as failed and updates the questline status accordingly.
    """
    while True:
        unchecked_missions = list(mongodb_connector.search_unchecked_child_missions())
        if len(unchecked_missions):
            print([ f"{m['id']}:{m['status']}" for m in unchecked_missions])
        time.sleep(2)
        dispatch_next_ready_child_mission()

        # Check for the executing missions and update their status
        for unchecked_mission in unchecked_missions:
            parent_quest_id = unchecked_mission['parentQuestId']
            order = unchecked_mission['order']
            child_status = pool_and_update_mission_status(unchecked_mission, db_rpc, mongodb_connector)

            # ASSISTANT HANDLES THE RESULT AND MARK THE MISSION CHECKED
            
            # If the mission is completed and there is no other mission to be executed, the quest was successfull !
            if child_status == MISSION_STATUS.SUCCEEDED:
                mongodb_connector.update_child_mission(unchecked_mission['_id'], managed_status=MANAGED_STATUS.CHECKED)
                if mongodb_connector.is_all_questline_missions_successfuly_completed(parent_quest_id):
                    update_questline_status(mongodb_connector, agent_connector_for_mission_thread, parent_quest_id, assignment_status=ASSIGNMENT_STATUS.SUCCEEDED, managed_status=MANAGED_STATUS.CHECKED)
                    
            # If the mission failed, we marked it as checked, register the failure in the questline and ask help to the AI.
            if child_status == MISSION_STATUS.FAILED:
                parent_quest_line = mongodb_connector.register_failure(parent_quest_id)
                mongodb_connector.update_child_mission(unchecked_mission['_id'], managed_status=MANAGED_STATUS.FIXING)

                # reach the failure limite, we give up fixing and fail the quest
                if parent_quest_line['numberFailures'] == FAILURE_LIMIT:
                    mongodb_connector.update_child_mission(unchecked_mission['_id'], managed_status=MANAGED_STATUS.CHECKED)
                    update_questline_status(mongodb_connector, agent_connector_for_mission_thread, parent_quest_id,  assignment_status=ASSIGNMENT_STATUS.FAILED, managed_status=QUEST_STATUS.CHECKED)
            

mission_watcher_thread = threading.Thread(target=child_missions_watcher, args=[helyos_client])



# Start the thread to watch for child missions and dispatch them
mission_watcher_thread.start()
        
# Subscribe to assignment messages
agent_connector.consume_assignment_messages(assignment_callback=register_questline_and_create_child_missions)

# Start listening for messages
agent_connector.start_listening()



