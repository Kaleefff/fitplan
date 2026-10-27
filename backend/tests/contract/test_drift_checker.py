"""Unit tests of the schema comparison used by the drift check."""

from tests.contract.drift import compare_schemas, compare_specs

CONTRACT = {
    "components": {
        "schemas": {
            "PageMeta": {
                "type": "object",
                "required": ["total"],
                "properties": {"total": {"type": "integer"}},
            },
            "ItemPage": {
                "allOf": [
                    {"$ref": "#/components/schemas/PageMeta"},
                    {
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                    },
                ]
            },
        }
    }
}
PAGE_REF = {"$ref": "#/components/schemas/ItemPage"}

# What FastAPI generates for the same page: one flat object.
FLAT_PAGE = {
    "type": "object",
    "required": ["total", "items"],
    "properties": {
        "total": {"type": "integer", "title": "Total"},
        "items": {"type": "array", "items": {"type": "string"}, "title": "Items"},
    },
}


def _compare(served: dict, contract: dict) -> list[str]:
    return compare_schemas({}, served, CONTRACT, contract, "X")


def test_flat_object_matches_all_of():
    assert _compare(FLAT_PAGE, PAGE_REF) == []


def test_missing_required_field_is_reported():
    served = {**FLAT_PAGE, "required": ["items"]}
    assert _compare(served, PAGE_REF) == ["X: required in the contract but optional ['total']"]


def test_array_item_type_is_compared():
    served = {**FLAT_PAGE, "properties": {**FLAT_PAGE["properties"], "items": {"type": "array"}}}
    assert _compare(served, PAGE_REF) == ["X.items[]: type [] != ['string']"]


def test_pydantic_optional_matches_type_list_with_null():
    served = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}
    assert _compare(served, {"type": ["string", "null"], "format": "date"}) == []


def test_null_allowed_on_one_side_only_is_reported():
    served = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert _compare(served, {"type": "string"}) == ["X: type ['null', 'string'] != ['string']"]


def test_enum_values_are_compared():
    contract = {"type": "string", "enum": ["a", "b"]}
    assert _compare({"type": "string", "enum": ["b", "a"]}, contract) == []
    assert _compare({"type": "string", "enum": ["a"]}, contract) == ["X: enum ['a'] != ['a', 'b']"]
    assert _compare({"type": "string", "enum": ["a", "b", "c"]}, contract) == [
        "X: enum ['a', 'b', 'c'] != ['a', 'b']"
    ]


def test_path_item_parameters_count_for_every_operation():
    param = {"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}}
    operation = {"operationId": "deleteItem", "responses": {}}
    served = {
        "paths": {"/api/v1/items/{item_id}": {"delete": {**operation, "parameters": [param]}}}
    }
    contract = {"paths": {"/items/{item_id}": {"parameters": [param], "delete": operation}}}
    assert compare_specs(served, contract) == []


def test_null_of_an_optional_query_parameter_is_ignored():
    def spec(schema, prefix=""):
        param = {"name": "from", "in": "query", "required": False, "schema": schema}
        return {
            "paths": {f"{prefix}/items": {"get": {"operationId": "list", "parameters": [param]}}}
        }

    nullable = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}
    plain = {"type": "string", "format": "date"}
    assert compare_specs(spec(nullable, "/api/v1"), spec(plain)) == []
    assert compare_specs(spec({"type": "integer"}, "/api/v1"), spec(plain)) != []
