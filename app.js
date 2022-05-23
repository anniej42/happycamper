// // const yaml = require("js-yaml");
// var editor = ace.edit("editor");
// const fs = require("file-system");
// editor.setTheme("ace/theme/tomorrow_night");
// var YamlMode = ace.require("ace/mode/yaml").Mode;
// editor.session.setMode(new YamlMode());

// var configPath = "config.yaml";
// try {
//   const config = jsyaml.load(fs.readFile("config.yaml", "utf8"));
//   $("#editor").html = config;
// } catch (e) {
//   console.log(e);
// }

const fs = require("fs");
const express = require("express");
const app = express();

app.use("/read_config", (req, res) => {
  if (e) throw e;

  // **modify your existing code here**
  fs.readFile("data.json", (e, data) => {
    if (e) throw e;
    res.send(data);
  });
});

app.listen(80);