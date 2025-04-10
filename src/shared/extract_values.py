def get_subfolder_name(file_path: str) -> str:
    path_sections = file_path.split("/")
    if len(path_sections) > 1:
        return path_sections[-2]
    return ""


def get_sub_subfolder_name(file_path: str) -> str:
    path_sections = file_path.split("/")
    if len(path_sections) > 2:
        return path_sections[-3]
    return ""


def get_file_name_with_extension(file_path: str) -> str:
    path_sections = file_path.split("/")
    return path_sections[-1]


def get_file_name_without_extension(file_path: str) -> str:
    file_name = get_file_name_with_extension(file_path)
    file_sections = file_name.split(".")
    if len(file_sections) > 1:
        return ".".join(file_sections[:-1])
    return file_name


def get_file_extension(file_path: str) -> str:
    file_name = get_file_name_with_extension(file_path)
    parts = file_name.split(".")
    if len(parts) > 1:
        return parts[-1]
    return ""


def get_id_rank(file_path: str) -> str:
    file_name = get_file_name_without_extension(file_path)
    parts = file_name.split("_")
    if len(parts) > 0:
        id_rank_part = parts[0]
        return id_rank_part[:]
    return ""


def get_id_candidate(file_path: str) -> str:
    file_name = get_file_name_without_extension(file_path)
    parts = file_name.split("_")
    if len(parts) > 1:
        id_candidate_part = parts[1]
        return id_candidate_part[:]
    return ""