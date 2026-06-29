from app.schemas.base import ApiBaseModel


class SampleSchema(ApiBaseModel):
    driver_name: str
    created_at: str


def test_base_schema_serializes_snake_case_as_camel_case() -> None:
    schema = SampleSchema(driver_name="Yewon", created_at="2026-06-28T03:10:00.000000Z")

    payload = schema.model_dump(by_alias=True)

    assert payload == {
        "driverName": "Yewon",
        "createdAt": "2026-06-28T03:10:00.000000Z",
    }


def test_base_schema_can_populate_by_alias() -> None:
    schema = SampleSchema(driverName="Yewon", createdAt="2026-06-28T03:10:00.000000Z")

    assert schema.driver_name == "Yewon"
    assert schema.created_at == "2026-06-28T03:10:00.000000Z"
