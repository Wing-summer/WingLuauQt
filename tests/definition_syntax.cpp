// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include <Luau/Parser.h>
#include <Luau/Frontend.h>
#include <Luau/BuiltinDefinitions.h>
#include <Luau/ConfigResolver.h>
#include <Luau/Module.h>
#include <Luau/Error.h>
#include <Luau/TypeArena.h>
#include <Luau/Allocator.h>
#include <Luau/Ast.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>

LUAU_FASTFLAG(LuauIntegerType2)

struct ProbeResolver : Luau::NullFileResolver {
    std::string probe;
    std::optional<Luau::SourceCode> readSource(const Luau::ModuleName& name) override {
        if (name == "@probe") return Luau::SourceCode{probe, Luau::SourceCode::Module};
        return std::nullopt;
    }
};

int main(int argc, char** argv)
{
    FFlag::LuauIntegerType2.value = true;
    std::string probePath;
    int lastDefinition = 0;
    bool merge = false;
    std::vector<std::string> definitions;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--merge") { merge = true; continue; }
        if (std::string(argv[i]).rfind("--probe=", 0) == 0) {
            probePath = std::string(argv[i]).substr(8);
            continue;
        }
        lastDefinition = i;
        definitions.emplace_back(argv[i]);
        std::ifstream input(argv[i]);
        if (!input) return 2;
        std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
        Luau::Allocator allocator;
        Luau::AstNameTable names(allocator);
        Luau::ParseOptions options;
        options.allowDeclarationSyntax = true;
        auto result = Luau::Parser::parse(source.data(), source.size(), names, allocator, options);
        for (const auto& error : result.errors)
            std::cerr << argv[i] << ':' << error.getLocation().begin.line + 1 << ": " << error.getMessage() << '\n';
        if (!result.errors.empty()) return 1;
    }
    if (lastDefinition) {
        ProbeResolver files;
        Luau::NullConfigResolver config;
        Luau::Frontend frontend(Luau::SolverMode::New, &files, &config);
        Luau::registerBuiltinGlobals(frontend, frontend.globals);
        Luau::unfreeze(frontend.globals.globalTypes);
        if (!merge) definitions = {argv[lastDefinition]};
        for (const std::string &path : definitions) {
            std::ifstream input(path);
            std::string source{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
            auto result = frontend.loadDefinitionFile(frontend.globals, frontend.globals.globalScope, source, path, false);
            if (result.module) {
                for (const auto &error : result.module->errors)
                    std::cerr << path << ':' << error.location.begin.line + 1 << ": " << Luau::toString(error) << '\n';
            }
            if (!result.success) return 1;
        }
        if (!probePath.empty()) {
            std::ifstream probe(probePath);
            if (!probe) return 2;
            files.probe.assign(std::istreambuf_iterator<char>(probe), std::istreambuf_iterator<char>());
            Luau::freeze(frontend.globals.globalTypes);
            auto checked = frontend.check("@probe");
            for (const auto& error : checked.errors)
                std::cerr << error.location.begin.line + 1 << ": " << Luau::toString(error) << '\n';
            if (!checked.errors.empty()) return 1;
        }
    }
    return 0;
}
