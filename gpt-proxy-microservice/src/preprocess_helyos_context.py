


def  get_neareset_trailer_from_objs(target_name, trailers, map_objects):
    """
    Get the nearest trailer to the target_id
    """
    target = next((t for t in map_objects if t['name'] == target_name), None) # find target in context
    x = target['metadata']['x']
    y = target['metadata']['y']
    
    # make a list of distances between trailer and targets
    distances = []
    for trailer in trailers:
        trailer_x = trailer['x']
        trailer_y = trailer['y']
        distance = ((trailer_x - x)**2 + (trailer_y - y)**2)**0.5
        distances.append(distance)
    min_distance = min(distances)

    # get the trailer name with the smallest distance to the map object or select UNKNOWN trailer
    if min_distance < 50000:
        nereast_trailer = trailers[distances.index(min_distance)]  
    else:
        nereast_trailer = {'uuid':'UNKNOWN'}   

    return nereast_trailer, min_distance



def  get_neareset_trailer(target, trailers):
    """
    Get the nearest trailer to the target
    """
    x = target['metadata']['x']
    y = target['metadata']['y']
    
    # make a list of distances between trailer and targets
    distances = []
    for trailer in trailers:
        trailer_x = trailer['x']
        trailer_y = trailer['y']
        distance = ((trailer_x - x)**2 + (trailer_y - y)**2)**0.5
        distances.append(distance)
    min_distance = min(distances)

    # get the trailer name with the smallest distance to the map object or select UNKNOWN trailer
    if min_distance < 50000:
        nereast_trailer = trailers[distances.index(min_distance)]  
    else:
        nereast_trailer = {'uuid':'UNKNOWN'}   

    return nereast_trailer, min_distance



def pre_process_map_objects(map_objects, trucks, trailers):
    """
    Pre-process map objects to extract relevant data and the nearest trailer to each target.
    """
    # Filter map objects to include only those with 'name' and 'metadata' keys
    targets = [obj for obj in map_objects if 'name' in obj and 'metadata' in obj]

    processed_targets = []
    for target in targets:
        # Get the target name and position
        target_name = target['name']
        target_position = {**target['metadata']}
        
        # Find the nearest trailer to the target
        # nearest_trailer, distance = get_neareset_trailer(target_name, trailers, filtered_map_objects)
        nearest_trailer, distance = get_neareset_trailer(target, trailers)
        
        # Add the trailer information to the target object
        processed_target = {"id": target["id"], "name": target_name, "position": target_position}
        processed_target['nearest_trailer'] = nearest_trailer['uuid'] if nearest_trailer else None
        processed_target['distance_to_nearest_trailer'] = distance
        processed_targets.append(processed_target)

    return processed_targets




def findStep(list_of_dicts, value): 
    for d in list_of_dicts:
        if 'step' in d and d['step'] == value:
            return d['response']
    return None

