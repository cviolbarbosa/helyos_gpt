from database_interface import MISSION_STATUS, MANAGED_STATUS
from helyos_agent_sdk.models import AssignmentCurrentStatus, ASSIGNMENT_STATUS


def dispatch_mission_to_helyos(mission, mission_rpc, mongodb_connector):
        print("dispatching  mission to helyos", mission)
        rpc_result = mission_rpc.call(
                    mission_name= mission['workProcessTypeName'],
                    data=mission['data'],
                    agent_uuids=mission['agentUuids'],
        )
        mongodb_connector.update_child_mission(mission['_id'],
                                            mission_id= rpc_result['work_process_id'],
                                            mission_status=MISSION_STATUS.EXECUTING,
                                            managed_status=MANAGED_STATUS.UNCHECKED)



def update_questline_status(mongodb_connector, agent_connector, parent_quest_id, assignment_status, managed_status):
    updated_quest = mongodb_connector.update_questline(parent_quest_id, assignment_status, managed_status)
    assignment_status_obj = AssignmentCurrentStatus(id=updated_quest['assignmentId'],status=assignment_status, result={})
    agent_connector.publish_state( status='free', assignment_status=assignment_status_obj )
    print("update_questline_status", parent_quest_id, updated_quest['assignmentId'], assignment_status, managed_status)
    
       
        
def pool_and_update_mission_status(mission, db_rpc, mongodb_connector):
    if (mission['id']):
        fresh_mission = db_rpc.call({'query': 'missionsById', 'conditions': {"id": int(mission['id'])}})
        
        mongodb_connector.update_child_mission(mission['_id'],
                                               mission_status=fresh_mission['status'],
                                               )
        
        return fresh_mission['status']
    return mission['status']