"""Inputs and result contracts for the native FS26 engineering solvers."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

ResistanceMethod = Literal["oortmerssen", "hollenbach", "fung"]
PerformanceMethod = Literal["oortmerssen", "hollenbach", "fung", "propeller1", "propeller2", "propeller3", "propeller5"]
NATIVE_FIELDS = {
    "oortmerssen": ({"OortSolver": 0, "ComboBox": 0}, "oortmerssen"),
    "hollenbach": ({"HolSolver": 0}, "hollenbach"),
    "fung": ({"FungSolver": 0}, "fung"),
    "propeller1": ({"DesignSolver": 0}, "propeller_design"),
    "propeller2": ({"DesignSolver": 0}, "propeller_design"),
    "propeller3": ({"PassportSolver": 0}, "propulsion_passport"),
    "propeller5": ({"ComboBox": 0}, "b_series"),
}
DIAGRAM_FIELD = {"propeller1": "Edit14", "propeller2": "Edit12", "propeller3": "Edit7"}
Parameter = Annotated[float, Field(strict=True, allow_inf_nan=False)] | Annotated[bool, Field(strict=True)]
Values = dict[str, Parameter]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Coordinate = Annotated[float, Field(ge=-1e9, le=1e9, strict=True)]
Positive = Annotated[float, Field(gt=0, le=1e9, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, le=1e9, strict=True)]
Angle = Annotated[float, Field(ge=-180, le=180, strict=True)]
Criterion = tuple[Annotated[float, Field(ge=0, le=180, strict=True)], Nonnegative]


def increasing(values: list[float]) -> list[float]:
    if any(a >= b for a, b in zip(values, values[1:])):
        raise ValueError("Heel angles must be strictly increasing")
    return values


Angles = Annotated[list[Angle], Field(min_length=1, max_length=181), AfterValidator(increasing)]


class AnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Load(AnalysisInput):
    name: Name
    x: Coordinate
    y: Coordinate
    z: Coordinate


class FixedLoad(Load):
    kind: Literal["fixed"]
    mass: Nonnegative


class FluidLoad(Load):
    density: Positive
    fill: Annotated[float, Field(ge=0, le=100, strict=True)]


class RectangularTank(FluidLoad):
    kind: Literal["tanks"]
    length: Positive
    width: Positive
    height: Positive


class CylindricalTank(FluidLoad):
    kind: Literal["cylinders"]
    length: Positive
    diameter: Positive


class SphericalTank(FluidLoad):
    kind: Literal["spheres"]
    diameter: Positive


class TrapezoidalTank(FluidLoad):
    kind: Literal["trapezoids"]
    length: Positive
    bottom_width: Positive
    top_width: Positive
    height: Positive


LoadItem = Annotated[FixedLoad | RectangularTank | CylindricalTank | SphericalTank | TrapezoidalTank,
                     Field(discriminator="kind")]


class LoadCase(AnalysisInput):
    name: Name
    items: Annotated[list[LoadItem], Field(max_length=133)] = Field(default_factory=list)


class LoadingBook(AnalysisInput):
    shared_items: Annotated[list[LoadItem], Field(max_length=132)] = Field(default_factory=list)
    cases: Annotated[list[LoadCase], Field(min_length=1, max_length=100)]
    criteria: Annotated[list[Criterion], Field(max_length=32)] = Field(default_factory=list)

    def native(self) -> dict:
        data = self.model_dump(mode="json")
        return {
            "version": 4,
            "criteria": data["criteria"],
            "shared_items": data["shared_items"],
            "cases": [[case["name"], case["items"]] for case in data["cases"]],
        }


class SpeedRange(AnalysisInput):
    start_kn: Nonnegative
    design_kn: Positive
    end_kn: Positive

    @model_validator(mode="after")
    def ordered(self):
        if not self.start_kn < self.design_kn < self.end_kn:
            raise ValueError("Speed range requires start < design < end")
        return self

    def native(self) -> dict:
        # The legacy field StepSpeedBox contains the maximum speed, not a step size.
        return {"StartSpeedBox": self.start_kn, "EndSpeedBox": self.design_kn, "StepSpeedBox": self.end_kn}


def native_values(calculator: PerformanceMethod, values: Values) -> dict:
    forced, _ = NATIVE_FIELDS[calculator]
    for key, value in forced.items():
        if values.get(key, value) != value:
            raise ValueError(f"{key} must be {value} for the native {calculator} solver")
    if key := DIAGRAM_FIELD.get(calculator):
        if key in values and values[key] not in (1, 2, 3, 4):
            raise ValueError(f"{key} must select a native Wageningen B-series diagram (1 to 4)")
    return {**values, **forced}
