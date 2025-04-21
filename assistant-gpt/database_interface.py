
from pymongo import MongoClient
from enum import Enum

class MISSION_STATUS(str, Enum):
    SUCCEEDED = 'succeeded'
    CANCELED = 'canceled'
    FAILED = 'failed'
    EXECUTING = 'executing'
    


class MANAGED_STATUS(str, Enum):
    UNCHECKED = 'unchecked'
    CHECKED = 'checked'
    WAITING = 'waiting'
    FIXING = 'fixing'

class QUEST_STATUS(str, Enum):
    UNCHECKED = 'unchecked'
    CHECKED = 'checked'
    WAITING = 'waiting'
    CREATING = 'creating'
    EXECUTING = 'executing'
    UPDATING = 'updating'
    

class MongoDBConnector:
    def __init__(self, uri, db_name):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        # Two separate collections: one for assignments coming directly from HelyOS Core (Questlines)
        # and one for assignments sent to another agents (ChildMissions).
        self.parent_collection = self.db['Questlines']
        self.child_collection = self.db['ChildMissions']

    def create_questline(self, prompt, assignment_id,  mission_id, data, assignment_status, quest_state):
        questline = {
            # "_id": internal mongo db index
            "prompt": prompt,                 # received from user
            "assignmentId": assignment_id,    # received from helyOS
            "workProcessId": mission_id,      # received from helyOS
            "assignmentStatus": assignment_status,  # reported to helyOS
            "workProcessStatus": '',                # received from helyOS
            "questlineStatus": quest_state,         # managed by this assistant
            "data": data,
            "numberFailures" : 0
        }
        insert_result = self.parent_collection.insert_one(questline)
        created_questline = self.parent_collection.find_one({'_id': insert_result.inserted_id})
        return created_questline

    def create_child_mission(self, id, status, agent_uuids, parent_quest_id, order, data, work_process_type_name):
        mission = {
            # "_id": internal mongo db index
            
            # These are the exact helyOS work_process (mission) fields
            "id": None, # Work process ID, only available when mission is dispatched
            'workProcessTypeName': work_process_type_name,
            "data": data,
            "status": status,  # Work process status received from helyOS
            "agentUuids": agent_uuids,
            
            # Those are additional fields controlled by the assitant            
            "parentQuestId": parent_quest_id,
            "assistantManagedStatus": MANAGED_STATUS.WAITING, # managed by this assistant
            "order": order
        }
        return self.child_collection.insert_one(mission).inserted_id

    def get_full_questline(self, id):
        """Return questline document with all related child missions included as a nested list."""
        questline = self.parent_collection.find_one({'_id': id})
        if not questline:
            return None
        
        child_missions = list(self.child_collection.find({'parentQuestId': id}))
        questline['childMissions'] = child_missions
        return questline
        
    def update_questline(self, id, assignment_status, managed_status):
        self.parent_collection.update_one({"_id": id}, {"$set": {"assignmentStatus": assignment_status, "questlineStatus": managed_status}})
        return self.parent_collection.find_one({'_id': id})

    def register_failure(self, id):
        self.parent_collection.update_one(
            {"_id": id},
            {"$inc": {"numberFailures": 1}}
        )
        return self.parent_collection.find_one({'_id': id})
        

    def update_child_mission(self, mongo_id, mission_id=None, mission_status=None, managed_status=None):
        update_fields = {}
        if mission_status is not None:
            update_fields["status"] = mission_status
        if mission_id is not None:
            update_fields["id"] = mission_id
        if managed_status is not None:
            update_fields["assistantManagedStatus"] = managed_status
        if update_fields:
            self.child_collection.update_one({"_id": mongo_id}, {"$set": update_fields})

    def is_all_questline_missions_successfuly_completed(self, id):
        child_missions = self.child_collection.find({"parentQuestId": id})
        for child_mission in child_missions:
            if child_mission["assistantManagedStatus"] != MANAGED_STATUS.CHECKED or child_mission["status"] != MISSION_STATUS.SUCCEEDED:
                return False
        return True


    def search_child_waiting_missions(self):
        executing_questlines = self.parent_collection.find({"questlineStatus": QUEST_STATUS.EXECUTING})
        executing_ids = [q["_id"] for q in executing_questlines]

        return list(self.child_collection.find({
            "assistantManagedStatus": MANAGED_STATUS.WAITING,
            "parentQuestId": {"$in": executing_ids}
        }))

    def delete_waiting_child_missions(self, parent_quest_id):
        result = self.child_collection.delete_many({
            "assistantManagedStatus": "waiting",
            "parentQuestId": parent_quest_id
        })
        return result.deleted_count     
    
    def search_unchecked_child_missions(self):
        return self.child_collection.find({"assistantManagedStatus": MANAGED_STATUS.UNCHECKED})
    
    def search_child_unchecked_missions(self):
        return self.child_collection.find({"status": "executing"})

    def search_child_missions(self, parent_quest_id, order):
        return self.child_collection.find({"parentQuestId": parent_quest_id, "order": order})

    def search_non_completed_child_missions(self, parent_quest_id):
        return self.child_collection.find({"parentQuestId": parent_quest_id, "status": {"$ne": "completed"}})

    def search_failed_child_missions(self, parent_quest_id):
        return self.child_collection.find({"parentQuestId": parent_quest_id, "status": "failed"})

    def delete_all_missions(self):
        self.parent_collection.delete_many({})
        self.child_collection.delete_many({})

    def list_all_child_missions(self):
        return list(self.child_collection.find())