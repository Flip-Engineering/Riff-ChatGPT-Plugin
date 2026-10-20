# The same beam relocation and Rust notice rules used by the desktop packager.
Code.require_file("installer/scripts/rust_notices.exs", Path.expand(Enum.at(System.argv(), 1)))

defmodule Riff.ChatGPT.PrepareControl do
  def run(runtime, source) do
    for path <- Path.wildcard(Path.join(runtime, "lib/*/ebin/*.beam")) do
      {:ok, _module, chunks} = :beam_lib.all_chunks(String.to_charlist(path))
      rewritten =
        Enum.flat_map(chunks, fn
          {~c"Line", data} = chunk ->
            if :binary.match(data, source) == :nomatch, do: [chunk], else: []
          {~c"Attr", data} ->
            [{~c"Attr", data |> :erlang.binary_to_term() |> relocate(source) |> :erlang.term_to_binary()}]
          {~c"LitT", data} -> [{~c"LitT", literals(data, source)}]
          chunk -> [chunk]
        end)
      {:ok, binary} = :beam_lib.build_module(rewritten)
      File.write!(path, binary)
    end
    {rust, 0} = System.cmd("rustc", ["--print", "sysroot"])
    Riff.Installer.RustNotices.copy!(String.trim(rust), Path.join(runtime, "licenses/rust"))
  end

  defp literals(<<size::32, data::binary>>, source) do
    data = if size == 0, do: data, else: :zlib.uncompress(data)
    <<count::32, values::binary>> = data
    rewritten = <<count::32>> <> terms(values, source)
    if size == 0, do: <<0::32, rewritten::binary>>, else: <<byte_size(rewritten)::32, :zlib.compress(rewritten)::binary>>
  end
  defp terms(<<>>, _source), do: <<>>
  defp terms(<<size::32, value::binary-size(size), rest::binary>>, source) do
    encoded = value |> :erlang.binary_to_term() |> relocate(source) |> :erlang.term_to_binary()
    <<byte_size(encoded)::32, encoded::binary>> <> terms(rest, source)
  end
  defp relocate(value, source) when is_binary(value), do: :binary.replace(value, source, "riff-source", [:global])
  defp relocate([], _source), do: []
  defp relocate([head | tail] = value, source) do
    if List.ascii_printable?(value),
      do: value |> List.to_string() |> relocate(source) |> String.to_charlist(),
      else: [relocate(head, source) | relocate(tail, source)]
  end
  defp relocate(value, source) when is_tuple(value), do: value |> Tuple.to_list() |> Enum.map(&relocate(&1, source)) |> List.to_tuple()
  defp relocate(value, source) when is_map(value), do: Map.new(Map.to_list(value), fn {key, item} -> {relocate(key, source), relocate(item, source)} end)
  defp relocate(value, _source), do: value
end

[runtime, source] = System.argv()
Riff.ChatGPT.PrepareControl.run(Path.expand(runtime), Path.expand(source))
