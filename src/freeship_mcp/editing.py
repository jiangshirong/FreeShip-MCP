"""Typed, explicit local edits; no inferred shape targets."""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

Index = Annotated[int, Field(ge=0, strict=True)]
Indices = Annotated[list[Index], Field(min_length=1, max_length=10000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_indices(self):
        ids = getattr(self, "point_indices", None)
        if ids is not None and len(ids) != len(set(ids)):
            raise ValueError("Point indices must be unique")
        return self


class PointMove(StrictModel):
    index: Index
    x_m: float | None = None
    y_m: float | None = None
    z_m: float | None = None

    @model_validator(mode="after")
    def coordinates(self):
        if all(v is None for v in (self.x_m, self.y_m, self.z_m)):
            raise ValueError("Specify at least one coordinate")
        return self


class MovePoints(StrictModel):
    action: Literal["move_points"]
    points: Annotated[list[PointMove], Field(min_length=1, max_length=10000)]

    @model_validator(mode="after")
    def unique_points(self):
        if len({p.index for p in self.points}) != len(self.points):
            raise ValueError("Duplicate point move")
        return self


class TranslatePoints(StrictModel):
    action: Literal["translate_points"]
    point_indices: Indices
    dx_m: float = 0
    dy_m: float = 0
    dz_m: float = 0


class AlignPoints(StrictModel):
    action: Literal["align_points"]
    point_indices: Indices
    axis: Literal["x", "y", "z"]
    value_m: float


class RelaxPoints(StrictModel):
    action: Literal["relax_points"]
    point_indices: Indices
    relaxation: Annotated[float, Field(gt=0, le=1)]
    iterations: Annotated[int, Field(ge=1, le=100)] = 1
    preserve_boundary: bool = True
    preserve_creases: bool = True


class SplitEdge(StrictModel):
    action: Literal["split_edge"]
    edge_index: Index
    fraction: Annotated[float, Field(gt=0, lt=1)] = .5


class SplitFace(StrictModel):
    action: Literal["split_face"]
    face_index: Index
    point_indices: Annotated[list[Index], Field(min_length=2, max_length=2)]


class AddFace(StrictModel):
    action: Literal["add_face"]
    point_indices: Annotated[list[Index], Field(min_length=3, max_length=100)]
    layer_index: Index


class DeleteFace(StrictModel):
    action: Literal["delete_face"]
    face_index: Index


class SetCrease(StrictModel):
    action: Literal["set_edge_crease"]
    edge_index: Index
    crease: bool


LocalEdit = Annotated[Union[MovePoints, TranslatePoints, AlignPoints, RelaxPoints, SplitEdge,
                            SplitFace, AddFace, DeleteFace, SetCrease], Field(discriminator="action")]
