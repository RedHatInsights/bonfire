from bonfire_lib.pools import list_pools, get_pool_capacity


class TestListPools:
    def test_returns_structured_output(self, mock_client, sample_pool):
        mock_client.list_pools.return_value = [sample_pool]

        result = list_pools(mock_client)

        assert len(result) == 1
        pool = result[0]
        assert pool["name"] == "default"
        assert pool["description"] == "Default pool"
        assert pool["size"] == 5
        assert pool["size_limit"] == 10
        assert pool["ready"] == 3
        assert pool["creating"] == 1
        assert pool["reserved"] == 2

    def test_empty_list(self, mock_client):
        mock_client.list_pools.return_value = []
        result = list_pools(mock_client)
        assert result == []

    def test_multiple_pools(self, mock_client, sample_pool):
        pool2 = {
            "metadata": {"name": "minimal"},
            "spec": {"size": 2, "description": "Minimal pool"},
            "status": {"ready": 1, "creating": 0, "reserved": 1},
        }
        mock_client.list_pools.return_value = [sample_pool, pool2]

        result = list_pools(mock_client)
        assert len(result) == 2
        assert result[0]["name"] == "default"
        assert result[1]["name"] == "minimal"

    def test_missing_optional_fields(self, mock_client):
        pool = {
            "metadata": {"name": "sparse"},
            "spec": {},
            "status": {},
        }
        mock_client.list_pools.return_value = [pool]

        result = list_pools(mock_client)
        assert result[0]["description"] == ""
        assert result[0]["size"] == 0
        assert result[0]["size_limit"] is None
        assert result[0]["ready"] == 0
        assert result[0]["creating"] == 0
        assert result[0]["reserved"] == 0


class TestGetPoolCapacity:
    def test_existing_pool(self, mock_client, sample_pool):
        mock_client.get_pool.return_value = sample_pool

        result = get_pool_capacity(mock_client, "default")

        assert result is not None
        assert result["name"] == "default"
        assert result["size"] == 5
        assert result["size_limit"] == 10
        assert result["ready"] == 3

    def test_nonexistent_pool(self, mock_client):
        mock_client.get_pool.return_value = None

        result = get_pool_capacity(mock_client, "nonexistent")
        assert result is None
