from fastapi import APIRouter, Query
from app.backend.services import projects

router = APIRouter(prefix='/projects', tags=['projects'])


@router.get('')
def index():
    return projects.list_projects()


@router.post('', status_code=201)
def create(value: projects.ProjectInput):
    return projects.save_project(value)


@router.put('/{project_id}')
def save(project_id: str, value: projects.ProjectInput):
    return projects.save_project(value, project_id)


@router.delete('/{project_id}', status_code=204)
def delete(project_id: str, revision: int = Query(ge=1)):
    projects.delete_project(project_id, revision)
