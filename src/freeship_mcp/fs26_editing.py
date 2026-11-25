"""FS26 editing inputs use native entity IDs and document units."""
from collections import Counter
from math import fsum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

EntityId = Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
Coordinate = Annotated[float, Field(strict=True, ge=-1e9, le=1e9)]
Position = tuple[Coordinate, Coordinate, Coordinate]
GridSize = Annotated[int, Field(strict=True, ge=2, le=100)]
Dimension = Annotated[float, Field(strict=True, gt=0, le=1e9)]


def unique_ids(ids: list[int]) -> list[int]:
    if len(set(ids)) != len(ids):
        raise ValueError("Entity IDs must be unique")
    return ids


EntityIds = Annotated[list[EntityId], Field(min_length=1, max_length=10000), AfterValidator(unique_ids)]


class EditInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PointMove(EditInput):
    point_id: EntityId
    position: Position


class MovePoints(EditInput):
    action: Literal["move_points"]
    moves: Annotated[list[PointMove], Field(min_length=1, max_length=10000)]


class AddPoint(EditInput):
    action: Literal["add_point"]
    position: Position


class SplitEdge(EditInput):
    action: Literal["split_edge"]
    edge_id: EntityId


class SetCrease(EditInput):
    action: Literal["set_edge_crease"]
    edge_id: EntityId
    crease: Annotated[bool, Field(strict=True)]


class AddFace(EditInput):
    action: Literal["add_face"]
    ids: Annotated[list[EntityId], Field(min_length=3, max_length=4096), AfterValidator(unique_ids)]
    layer_id: EntityId


class SplitFace(EditInput):
    action: Literal["split_face"]
    face_id: EntityId
    point_ids: Annotated[list[EntityId], Field(min_length=2, max_length=2), AfterValidator(unique_ids)]


class DeleteFace(EditInput):
    action: Literal["delete_face"]
    face_id: EntityId


class RelaxPoints(EditInput):
    action: Literal["relax_points"]
    point_ids: EntityIds
    relaxation: Annotated[float, Field(strict=True, gt=0, le=1)]
    iterations: Annotated[int, Field(strict=True, ge=1, le=100)] = 1


class Lackenby(EditInput):
    layer_ids: EntityIds
    displacement: Annotated[float, Field(strict=True, gt=0)]
    lcb: Coordinate
    iterations: Annotated[int, Field(strict=True, ge=1, le=100)] = 30


FS26Edit = Annotated[
    MovePoints | AddPoint | SplitEdge | SetCrease | AddFace | SplitFace | DeleteFace | RelaxPoints,
    Field(discriminator="action"),
]


def edit_request(edit: FS26Edit | Lackenby, snapshot: dict) -> dict:
    if isinstance(edit, Lackenby):
        return {"method": "modeling", "operation": "lackenby", "ids": edit.layer_ids,
                "displacement": edit.displacement, "lcb": edit.lcb, "iterations": edit.iterations}
    operation = edit.action
    parameters = edit.model_dump(exclude={"action"})
    if isinstance(edit, MovePoints):
        unique_ids([move.point_id for move in edit.moves])
        return {"method": "move_points", **parameters}
    if isinstance(edit, RelaxPoints):
        return {"method": "move_points", "moves": relax_points(edit, snapshot)}
    if isinstance(edit, SplitFace):
        face = next((item for item in snapshot["control_faces"] if item["id"] == edit.face_id), None)
        if face is None or not set(edit.point_ids).issubset(face["points"]):
            raise ValueError("Split endpoints must belong to the selected face")
        a, b = sorted(edit.point_ids)
        if any(sorted((edge["a"], edge["b"])) == [a, b] for edge in snapshot["control_edges"]):
            raise ValueError("Split endpoints must form a new face diagonal")
        return {"method": "modeling", "operation": "connect_points", "ids": edit.point_ids}
    if isinstance(edit, DeleteFace):
        return {"method": "topology", "operation": "delete", "kind": "face", "ids": [edit.face_id]}
    if isinstance(edit, SetCrease):
        return {"method": "topology", "operation": "set_crease", "ids": [edit.edge_id], "crease": edit.crease}
    return {"method": "topology", "operation": operation, **parameters}


def relax_points(edit: RelaxPoints, snapshot: dict) -> list[dict]:
    points = {point["id"]: point for point in snapshot["control_points"]}
    neighbours = {point_id: [] for point_id in edit.point_ids}
    incidence = Counter()
    for face in snapshot["control_faces"]:
        vertices = face["points"]
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            if a in neighbours or b in neighbours:
                incidence[tuple(sorted((a, b)))] += 1
    protected = set()
    for edge in snapshot["control_edges"]:
        a, b = edge["a"], edge["b"]
        if a in neighbours:
            neighbours[a].append(b)
        if b in neighbours:
            neighbours[b].append(a)
        if (a in neighbours or b in neighbours) and (edge["crease"] or incidence[tuple(sorted((a, b)))] != 2):
            protected.update((a, b))
    if protected.intersection(neighbours):
        raise ValueError("Relaxation selection touches a crease or an open boundary")
    for point_id, adjacent in neighbours.items():
        point = points.get(point_id)
        if not point or not adjacent or not point["batch_movable"] or point["vertex_type"] == 3:
            raise ValueError(f"Point {point_id} is missing, isolated, locked, constrained or a corner")

    positions = {point_id: point["p"] for point_id, point in points.items()}
    for _ in range(edit.iterations):
        # All selected points use the same previous iteration.
        positions.update({
            point_id: [
                value + edit.relaxation * (fsum(positions[other][axis] for other in adjacent) / len(adjacent) - value)
                for axis, value in enumerate(positions[point_id])
            ]
            for point_id, adjacent in neighbours.items()
        })
    return [{"point_id": point_id, "position": positions[point_id]} for point_id in edit.point_ids]
